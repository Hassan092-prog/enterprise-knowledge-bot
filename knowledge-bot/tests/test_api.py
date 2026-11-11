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
    from api.dependencies import get_db as dep_get_db

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestingSessionLocal() as db:
        t = Tenant(id=1, name="Test Org", slug="test-org", monthly_token_budget=500000, current_month_tokens=0)
        u = User(id=1, username="testuser", role="admin", tenant_id=1, is_platform_admin=True)
        db.add(t)
        db.add(u)
        db.commit()

    orig_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[dep_get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)

@pytest.fixture
def mock_retriever():
    """Mock the Retriever singleton so we don't load real models or DBs."""
    mock_instance = MagicMock()
    mock_store = MagicMock()
    mock_store.delete_source.return_value = 1
    mock_instance.delete_document.return_value = 1
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
    def fake_stream(query, chunks, chat_history=None, graph_context=None, *args, **kwargs):
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


def test_platform_delete_tenant_full_cascade(client, mock_retriever, mock_upload_dir):
    """Verify platform tenant deletion revokes sessions, purges graph & storage, and blocks self-delete."""
    from api.dependencies import get_db as dep_get_db

    with TestingSessionLocal() as db:
        db.add(Tenant(id=99, name="Disposable Org", slug="disposable-org", status="active"))
        db.commit()

    mock_retriever._store.delete_all_tenant_chunks.return_value = 4
    mock_storage = MagicMock()
    mock_storage.list_objects.return_value = ["tenants/99/global/policy.pdf"]
    mock_graph = MagicMock()

    orig_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[dep_get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: _test_user

        # Self-deletion (tenant 1) rejected
        res_self = client.delete("/platform/tenants/1")
        assert res_self.status_code == 400

        with patch("src.sso.revocation.revoke_tenant_sessions") as mock_revoke, \
             patch("src.graph.get_graph_store", return_value=mock_graph), \
             patch("src.storage.get_storage_provider", return_value=mock_storage):
            res = client.delete("/platform/tenants/99")
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "purged"
            assert data["chunks_purged"] == 4
            mock_revoke.assert_called_once_with(99)
            mock_graph.delete_tenant_graph.assert_called_once_with(99)
            mock_storage.list_objects.assert_called_once_with(prefix="tenants/99/")
            mock_storage.delete_object.assert_called_once_with("tenants/99/global/policy.pdf")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)


def test_task_status_isolates_same_tenant_personal_tasks(client):
    """Non-admin User B in the same tenant cannot inspect User A's personal background task."""
    import api.main as main_mod
    from src.models import User

    fake_result = MagicMock()
    fake_result.state = "SUCCESS"
    fake_result.result = {
        "filename": "u1_private.pdf",
        "chunks": 3,
        "tenant_id": 1,
        "user_id": 1,
        "is_global": False,
    }
    fake_result.info = fake_result.result

    user_b = User(
        id=2,
        username="user_b",
        email="user_b@example.com",
        role="user",
        tenant_id=1,
        is_platform_admin=False,
    )

    from src.worker import celery_app

    orig_overrides = app.dependency_overrides.copy()
    try:
        with patch.object(celery_app, "AsyncResult", return_value=fake_result):
            # User B (same tenant, non-admin) must receive 403 on User 1's personal task
            app.dependency_overrides[get_current_user] = lambda: user_b
            res_b = client.get("/tasks/task_personal_u1")
            assert res_b.status_code == 403

            # Owner (User 1) can inspect their own personal task
            app.dependency_overrides[get_current_user] = lambda: _test_user
            res_a = client.get("/tasks/task_personal_u1")
            assert res_a.status_code == 200
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)


def test_download_and_delete_mixed_scope_not_fooled_by_first_metadata(client, mock_retriever, mock_upload_dir):
    """Ensure download/delete resolve caller's personal or global scope even when metadatas[0] belongs to another user."""
    import api.main as main_mod
    from src.models import User

    user_b = User(
        id=2,
        username="user_b",
        email="user_b@example.com",
        role="user",
        tenant_id=1,
        is_platform_admin=False,
    )

    # Prepare mixed metadata where index 0 belongs to User 99 (different user in tenant 1)
    mock_retriever._store._collection.get.return_value = {
        "metadatas": [
            {"tenant_id": 1, "source": "report.pdf", "is_global": False, "user_id": 99},
            {"tenant_id": 1, "source": "report.pdf", "is_global": True, "user_id": 1},
            {"tenant_id": 1, "source": "report.pdf", "is_global": False, "user_id": 2},
        ]
    }

    u2_personal_dir = mock_upload_dir / "tenant_1" / "personal" / "2"
    u2_personal_dir.mkdir(parents=True, exist_ok=True)
    (u2_personal_dir / "report.pdf").write_bytes(b"user2-personal-pdf")

    orig_overrides = app.dependency_overrides.copy()
    try:
        app.dependency_overrides[get_current_user] = lambda: user_b
        with patch.object(main_mod, "get_tenant_upload_dir", return_value=mock_upload_dir / "tenant_1"):
            dl_res = client.get("/documents/report.pdf/download?scope=personal")
            assert dl_res.status_code == 200
            assert dl_res.content == b"user2-personal-pdf"

            del_res = client.delete("/documents/report.pdf?scope=personal")
            assert del_res.status_code == 200
            mock_retriever.delete_document.assert_called_with("report.pdf", user_id=2, tenant_id=1, is_global=False)

        # If ONLY User 99's personal file exists, User 2 must get 403
        mock_retriever._store._collection.get.return_value = {
            "metadatas": [
                {"tenant_id": 1, "source": "only_u99.pdf", "is_global": False, "user_id": 99},
            ]
        }
        res_forbidden_dl = client.get("/documents/only_u99.pdf/download")
        assert res_forbidden_dl.status_code == 403
        res_forbidden_del = client.delete("/documents/only_u99.pdf")
        assert res_forbidden_del.status_code == 403
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(orig_overrides)


def test_vector_store_chunk_ids_scoped_per_user_and_global():
    """Verify same-filename chunks get distinct chunk_ids for user_id=1, user_id=2, and is_global=True."""
    from langchain_core.documents import Document
    from src.retrieval.vector_store import VectorStore

    store = VectorStore.__new__(VectorStore)
    store._collection = MagicMock()
    store._collection.get.return_value = {"ids": []}
    store._bm25_indices = {}
    store._bm25_versions = {}
    store._mistral_client = None
    store._local_embedder = None
    store._embeddings = MagicMock()
    store._embeddings.embed_documents.return_value = [[0.1, 0.2]]
    store._build_bm25_for_tenant = MagicMock()

    captured_ids = []

    def _capture_ids(*args, **kwargs):
        ids_arg = kwargs.get("ids")
        if ids_arg is None and args:
            ids_arg = args[0]
        if ids_arg:
            captured_ids.extend(ids_arg)

    store._collection.add.side_effect = _capture_ids
    store._collection.upsert.side_effect = _capture_ids

    with patch("src.cache.bump_cache_version"):
        store.add_documents(
            [Document(page_content="chunk text", metadata={"source": "report.pdf", "chunk_id": "c0"})],
            user_id=1,
            is_global=False,
            tenant_id=1,
        )
        store.add_documents(
            [Document(page_content="chunk text", metadata={"source": "report.pdf", "chunk_id": "c0"})],
            user_id=2,
            is_global=False,
            tenant_id=1,
        )
        store.add_documents(
            [Document(page_content="chunk text", metadata={"source": "report.pdf", "chunk_id": "c0"})],
            user_id=1,
            is_global=True,
            tenant_id=1,
        )

    assert len(captured_ids) == 3
    assert len(set(captured_ids)) == 3
    assert "t1_u1_c0" in captured_ids
    assert "t1_u2_c0" in captured_ids
    assert "t1_g_c0" in captured_ids


def test_tabular_query_isolates_personal_csv_between_users(tmp_path):
    """User 2 must not read User 1's personal/1/secret.csv via disk or storage fallback."""
    from src.retrieval.tabular_agent import run_tabular_query

    tenant_dir = tmp_path / "tenant_1"
    u1_dir = tenant_dir / "personal" / "1"
    u1_dir.mkdir(parents=True, exist_ok=True)
    (u1_dir / "secret.csv").write_text("secret_col\nTOP_SECRET_VALUE\n", encoding="utf-8")

    mock_storage = MagicMock()
    mock_storage.download_file.side_effect = FileNotFoundError("not found")

    with patch("src.retrieval.tabular_agent.get_tenant_upload_dir", return_value=tenant_dir), \
         patch("src.retrieval.tabular_agent.UPLOAD_DIR", tmp_path), \
         patch("src.storage.get_storage_provider", return_value=mock_storage):
        result = run_tabular_query("list all rows", "secret.csv", tenant_id=1, user_id=2)

    assert "TOP_SECRET_VALUE" not in result
    mock_storage.list_objects.assert_not_called()


