import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import MagicMock, patch

from api.main import app, get_db
from api.dependencies import get_current_user
from src.database import Base
from src.models import User, Tenant

# Setup in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Create tables in the in-memory db
Base.metadata.create_all(bind=engine)

_test_user = User(
    id=1,
    username="testuser",
    role="admin",
    tenant_id=1,
    is_platform_admin=True
)

def override_get_current_user():
    return _test_user

app.dependency_overrides[get_current_user] = override_get_current_user

@pytest.fixture(autouse=True)
def clean_db():
    """Ensure the database is clean and seeded before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        t = Tenant(id=1, name="Test Org", slug="test-org", monthly_token_budget=500000, current_month_tokens=0)
        u = User(id=1, username="testuser", role="admin", tenant_id=1, is_platform_admin=True)
        db.add(t)
        db.add(u)
        db.commit()

@pytest.fixture
def mock_retriever():
    """Mock the Retriever singleton so we don't load real models or DBs."""
    mock_instance = MagicMock()
    mock_store = MagicMock()
    mock_store.delete_source.return_value = 1
    mock_instance._store = mock_store
    with patch("api.main.get_retriever", return_value=mock_instance), \
         patch("api.main.retriever", mock_instance):
        yield mock_instance

@pytest.fixture
def mock_upload_dir(tmp_path):
    """Prevent tests from writing uploaded files to the real data directory."""
    with patch("api.main.UPLOAD_DIR", tmp_path), \
         patch("api.main.get_tenant_upload_dir", return_value=tmp_path):
        yield tmp_path

@pytest.fixture
def mock_session_local():
    """Ensure the background generator writes to the test DB, not the real DB."""
    with patch("src.database.SessionLocal", TestingSessionLocal):
        yield

@pytest.fixture
def mock_stream_answer():
    """Prevent real LLM calls during streaming."""
    def fake_stream(query, chunks, chat_history=None):
        yield "This "
        yield "is "
        yield "a test answer."
    
    with patch("api.main.stream_answer", side_effect=fake_stream):
        yield

@pytest.fixture
def client(mock_retriever):
    with TestClient(app) as c:
        yield c

# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_readiness_check(client, mock_retriever):
    mock_retriever.heartbeat.return_value = 123456789
    with patch("src.storage.get_storage_provider") as mock_storage_factory:
        mock_storage = MagicMock()
        mock_storage.ping.return_value = True
        mock_storage.__class__.__name__ = "MockStorageProvider"
        mock_storage_factory.return_value = mock_storage
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data
        assert data["checks"]["database"]["status"] == "ok"
        assert data["checks"]["chromadb"]["status"] == "ok"
        assert data["checks"]["storage"]["status"] == "ok"

def test_security_headers(client):
    response = client.get("/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    assert "strict-origin-when-cross-origin" in response.headers["Referrer-Policy"]

def test_list_documents(client, mock_retriever):
    mock_retriever.list_sources_by_type.return_value = {
        "personal": ["personal.pdf"],
        "global": ["company_policy.pdf"]
    }
    response = client.get("/documents")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "global_documents" in data

def test_delete_document(client, mock_retriever, mock_upload_dir):
    mock_retriever._store._collection.get.return_value = {
        "metadatas": [{"is_global": 0, "user_id": 1}]
    }
    with patch("src.storage.get_storage_provider") as mock_storage:
        mock_storage.return_value = MagicMock()
        response = client.delete("/documents/annual_report.pdf")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
        assert response.json()["filename"] == "annual_report.pdf"

def test_upload_document(client, mock_retriever, mock_upload_dir):
    file_content = b"Dummy PDF content"
    files = {"file": ("test.pdf", file_content, "application/pdf")}
    
    with patch("src.storage.get_storage_provider") as mock_storage, \
         patch("src.worker.process_document.delay") as mock_delay:
        mock_storage.return_value = MagicMock()
        mock_task = MagicMock()
        mock_task.id = "task-uuid-1234"
        mock_delay.return_value = mock_task
        
        response = client.post("/upload", files=files)
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test.pdf"
        assert data["status"] == "processing"
        assert data["task_id"] == "task-uuid-1234"
        
        # Verify it rejected an invalid extension
        bad_files = {"file": ("test.exe", file_content, "application/x-msdownload")}
        response_bad = client.post("/upload", files=bad_files)
        assert response_bad.status_code == 400
        assert "Unsupported file type" in response_bad.json()["detail"]

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
    mock_retriever.list_sources.return_value = []
    mock_retriever.retrieve.return_value = []
    
    # 3. Post a query
    query_payload = {"query": "What is the revenue?", "session_id": session_id}
    response = client.post("/query", json=query_payload)
    
    assert response.status_code == 200
    assert "This is a test answer." in response.text
    
    # 4. Verify messages were saved to the DB (both user and assistant)
    msg_res = client.get(f"/sessions/{session_id}/messages")
    assert msg_res.status_code == 200
    messages = msg_res.json()
    
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the revenue?"
    assert messages[1]["role"] == "assistant"
    assert "This is a test answer." in messages[1]["content"]
