import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from api.main import app, get_db
from src.database import Base

# Setup in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Create tables in the in-memory db
Base.metadata.create_all(bind=engine)

@pytest.fixture(autouse=True)
def clean_db():
    """Ensure the database is clean before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

@pytest.fixture
def mock_retriever():
    """Mock the Retriever singleton so we don't load real models or DBs."""
    with patch("api.main.Retriever") as MockRetrieverClass:
        mock_instance = MagicMock()
        MockRetrieverClass.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def mock_upload_dir(tmp_path):
    """Prevent tests from writing uploaded files to the real data directory."""
    with patch("api.main.UPLOAD_DIR", tmp_path):
        yield tmp_path

@pytest.fixture
def mock_session_local():
    """Ensure the background generator writes to the test DB, not the real DB."""
    with patch("src.database.SessionLocal", TestingSessionLocal):
        yield

@pytest.fixture
def mock_stream_answer():
    """Prevent real LLM calls during streaming."""
    def fake_stream(query, chunks):
        yield "This "
        yield "is "
        yield "a test answer."
    
    with patch("api.main.stream_answer", side_effect=fake_stream):
        yield

@pytest.fixture
def client(mock_retriever):
    # Using 'with' triggers startup events which binds our mocked retriever
    with TestClient(app) as c:
        yield c

# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_list_documents(client, mock_retriever):
    mock_retriever.list_sources.return_value = ["annual_report.pdf", "data.csv"]
    response = client.get("/documents")
    assert response.status_code == 200
    assert response.json() == {"documents": ["annual_report.pdf", "data.csv"]}

def test_delete_document(client, mock_retriever):
    mock_retriever.delete_document.return_value = True
    response = client.delete("/documents/annual_report.pdf")
    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "filename": "annual_report.pdf"}
    mock_retriever.delete_document.assert_called_with("annual_report.pdf")

def test_upload_document(client, mock_retriever, mock_upload_dir):
    mock_result = MagicMock()
    mock_result.chunks_added = 12
    mock_retriever.ingest_file.return_value = mock_result
    
    file_content = b"Dummy PDF content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    
    response = client.post("/upload", files=files)
    assert response.status_code == 200
    assert response.json() == {"filename": "test.pdf", "chunks_added": 12}
    
    # Verify it rejected an invalid extension
    bad_files = {"file": ("test.exe", file_content, "application/x-msdownload")}
    response = client.post("/upload", files=bad_files)
    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

def test_create_and_list_sessions(client):
    # Create a session
    res1 = client.post("/sessions")
    assert res1.status_code == 200
    assert "id" in res1.json()
    assert res1.json()["title"] == "New Chat"
    session_id = res1.json()["id"]
    
    # List sessions
    res2 = client.get("/sessions")
    assert res2.status_code == 200
    sessions = res2.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id

def test_query_bot(client, mock_retriever, mock_stream_answer, mock_session_local):
    # 1. Create a session first
    session_res = client.post("/sessions")
    session_id = session_res.json()["id"]
    
    # 2. Mock retrieve returning dummy chunks
    mock_retriever.retrieve.return_value = []
    
    # 3. Post a query
    query_payload = {"query": "What is the revenue?", "session_id": session_id}
    response = client.post("/query", json=query_payload)
    
    assert response.status_code == 200
    # Streamed response should equal the concatenated chunks from our fake generator
    assert response.text == "This is a test answer."
    
    # 4. Verify messages were saved to the DB (both user and assistant)
    msg_res = client.get(f"/sessions/{session_id}/messages")
    assert msg_res.status_code == 200
    messages = msg_res.json()
    
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the revenue?"
    
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "This is a test answer."
