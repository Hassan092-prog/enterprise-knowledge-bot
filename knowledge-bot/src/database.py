import os
import secrets
from datetime import datetime
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from src.config import DATA_DIR, DATABASE_URL
from src.logger import get_logger

logger = get_logger(__name__)

# Ensure data directory exists for local fallback
DATA_DIR.mkdir(parents=True, exist_ok=True)

if DATABASE_URL:
    # Use PostgreSQL (Production Hardened Connection Pool)
    from src.config import (
        DB_POOL_SIZE,
        DB_MAX_OVERFLOW,
        DB_POOL_TIMEOUT,
        DB_POOL_RECYCLE,
    )
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=DB_POOL_RECYCLE,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
    )
else:
    # Fallback to local SQLite (Development)
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATA_DIR / 'chat.db'}"
    # Check_same_thread is needed only for SQLite
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


import re
import unicodedata

def slugify(text: str) -> str:
    """Convert text to URL/system safe slug using standard library only."""
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^\w\s-]', '', text.lower()).strip()
    return re.sub(r'[-\s]+', '-', text)

def generate_join_code() -> str:
    """Generate a clean, high-entropy 8-character join code."""
    return f"ORG-{secrets.token_hex(4).upper()}"


def run_db_migrations():
    """
    Run table creation, schema evolution (adding columns if missing),
    and bootstrap initial tenant and platform superadmin.
    """
    from src.models import (
        Tenant, User, ChatSession, AccessRequest, ActivityLog, PendingTransfer,
        KnowledgeNode, KnowledgeEdge
    )

    logger.info("Initializing database tables and running schema migration...")
    Base.metadata.create_all(bind=engine)

    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        with engine.connect() as conn:
            # 1. users table schema evolution
            if "users" in existing_tables:
                user_cols = {c["name"] for c in inspector.get_columns("users")}
                if "tenant_id" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN tenant_id INTEGER"))
                    logger.info("Added 'tenant_id' column to users table.")
                if "is_platform_admin" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_platform_admin BOOLEAN DEFAULT FALSE"))
                    logger.info("Added 'is_platform_admin' column to users table.")
                if "email" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR"))
                    logger.info("Added 'email' column to users table.")
                if "auth_provider" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN auth_provider VARCHAR DEFAULT 'local'"))
                    logger.info("Added 'auth_provider' column to users table.")
                if "oauth_id" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN oauth_id VARCHAR"))
                    logger.info("Added 'oauth_id' column to users table.")
                if "avatar_url" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))
                    logger.info("Added 'avatar_url' column to users table.")
                if engine.dialect.name == "postgresql":
                    try:
                        conn.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
                    except Exception:
                        pass
                conn.commit()

            # 1b. tenants table schema evolution
            if "tenants" in existing_tables:
                tenant_cols = {c["name"] for c in inspector.get_columns("tenants")}
                if "allowed_domains" not in tenant_cols:
                    conn.execute(text("ALTER TABLE tenants ADD COLUMN allowed_domains TEXT"))
                    logger.info("Added 'allowed_domains' column to tenants table.")
                if "monthly_token_budget" not in tenant_cols:
                    conn.execute(text("ALTER TABLE tenants ADD COLUMN monthly_token_budget INTEGER DEFAULT 500000"))
                    logger.info("Added 'monthly_token_budget' column to tenants table.")
                if "current_month_tokens" not in tenant_cols:
                    conn.execute(text("ALTER TABLE tenants ADD COLUMN current_month_tokens INTEGER DEFAULT 0"))
                    logger.info("Added 'current_month_tokens' column to tenants table.")
                if "budget_reset_at" not in tenant_cols:
                    conn.execute(text("ALTER TABLE tenants ADD COLUMN budget_reset_at TIMESTAMP"))
                    logger.info("Added 'budget_reset_at' column to tenants table.")
                conn.commit()

            # 2. chat_sessions table schema evolution
            if "chat_sessions" in existing_tables:
                session_cols = {c["name"] for c in inspector.get_columns("chat_sessions")}
                if "tenant_id" not in session_cols:
                    conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN tenant_id INTEGER"))
                    logger.info("Added 'tenant_id' column to chat_sessions table.")
                conn.commit()

            # 3. access_requests table schema evolution
            if "access_requests" in existing_tables:
                req_cols = {c["name"] for c in inspector.get_columns("access_requests")}
                if "tenant_id" not in req_cols:
                    conn.execute(text("ALTER TABLE access_requests ADD COLUMN tenant_id INTEGER"))
                    logger.info("Added 'tenant_id' column to access_requests table.")
                conn.commit()

            # 3b. chat_messages table schema evolution (Citation metadata)
            if "chat_messages" in existing_tables:
                msg_cols = {c["name"] for c in inspector.get_columns("chat_messages")}
                if "sources_json" not in msg_cols:
                    conn.execute(text("ALTER TABLE chat_messages ADD COLUMN sources_json TEXT"))
                    logger.info("Added 'sources_json' column to chat_messages table.")
                conn.commit()
            # 4. Ensure fk_tenant_superadmin_user_id has ON DELETE SET NULL in PostgreSQL
            if engine.dialect.name == "postgresql" and "tenants" in existing_tables:
                try:
                    conn.execute(text("""
                        DO $$
                        BEGIN
                            ALTER TABLE tenants DROP CONSTRAINT IF EXISTS fk_tenant_superadmin_user_id;
                            ALTER TABLE tenants ADD CONSTRAINT fk_tenant_superadmin_user_id 
                                FOREIGN KEY (superadmin_user_id) REFERENCES users(id) ON DELETE SET NULL;
                        EXCEPTION
                            WHEN others THEN NULL;
                        END $$;
                    """))
                    conn.commit()
                except Exception as fk_err:
                    logger.warning(f"FK constraint update notice: {fk_err}")

            # 5. Synchronize primary key sequences for PostgreSQL
            if engine.dialect.name == "postgresql":
                try:
                    conn.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
                    conn.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
                    conn.commit()
                    logger.info("Synchronized PostgreSQL auto-increment sequences.")
                except Exception as seq_err:
                    logger.warning(f"Sequence sync notice: {seq_err}")

    except Exception as e:
        logger.warning(f"Schema evolution notice (may already be up to date): {e}")

    # 4. Data bootstrapping
    with SessionLocal() as db:
        try:
            default_tenant = db.query(Tenant).filter(Tenant.id == 1).first()
            if not default_tenant:
                default_tenant = db.query(Tenant).first()
                if not default_tenant:
                    default_tenant = Tenant(
                        id=1,
                        name="Default Organization",
                        slug="default",
                        status="active",
                        join_code=generate_join_code()
                    )
                    db.add(default_tenant)
                    db.flush()
                    logger.info("Created Default Organization tenant.")

            # Assign orphaned users to default tenant
            orphaned_users = db.query(User).filter(User.tenant_id.is_(None)).all()
            for u in orphaned_users:
                u.tenant_id = default_tenant.id

            # Ensure platform superadmin exists
            superadmin = db.query(User).filter(User.role == "superadmin").first()
            if not superadmin:
                admin_user = db.query(User).filter(User.role == "admin").first()
                target_user = admin_user or db.query(User).order_by(User.id.asc()).first()
                if target_user:
                    target_user.role = "superadmin"
                    target_user.is_platform_admin = True
                    if not target_user.tenant_id:
                        target_user.tenant_id = default_tenant.id
                    superadmin = target_user
                    logger.info(f"Promoted user '{target_user.username}' to SuperAdmin and Platform Admin.")

            if superadmin and default_tenant.superadmin_user_id is None:
                default_tenant.superadmin_user_id = superadmin.id

            if not default_tenant.join_code:
                default_tenant.join_code = generate_join_code()

            db.commit()

            # Synchronize sequences after bootstrapping
            if engine.dialect.name == "postgresql":
                try:
                    db.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
                    db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
                    db.commit()
                except Exception as seq_err:
                    logger.warning(f"Post-bootstrap sequence sync notice: {seq_err}")

            logger.info("Database bootstrap completed successfully.")
        except Exception as e:
            db.rollback()
            logger.error(f"Error during database bootstrap: {e}")


def check_and_reset_tenant_budget(tenant, db: Session) -> bool:
    """
    Check if tenant's monthly token budget should be reset (if budget_reset_at is in a previous month).
    Returns True if a reset occurred, False otherwise.
    """
    now = datetime.utcnow()
    current_month_start = datetime(now.year, now.month, 1)

    if tenant.budget_reset_at is None:
        tenant.budget_reset_at = current_month_start
        db.commit()
        return False

    if tenant.budget_reset_at < current_month_start:
        tenant.current_month_tokens = 0
        tenant.budget_reset_at = current_month_start
        db.commit()
        logger.info(f"Monthly token budget reset to 0 for tenant '{tenant.name}' (ID: {tenant.id}) for {current_month_start.strftime('%Y-%m')}.")
        return True

    return False


def record_tenant_token_usage(tenant_id: int, tokens_used: int, db: Session) -> int:
    """
    Atomically increment a tenant's current_month_tokens by tokens_used.
    Works across PostgreSQL and SQLite. Returns new current_month_tokens value.
    """
    from src.models import Tenant
    if tokens_used <= 0:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        return tenant.current_month_tokens if tenant else 0

    db.execute(
        text("UPDATE tenants SET current_month_tokens = COALESCE(current_month_tokens, 0) + :tokens WHERE id = :tenant_id"),
        {"tokens": tokens_used, "tenant_id": tenant_id}
    )
    db.commit()
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant.current_month_tokens if tenant else 0

