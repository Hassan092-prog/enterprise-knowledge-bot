import os
import secrets
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import DATA_DIR, DATABASE_URL
from src.logger import get_logger

logger = get_logger(__name__)

# Ensure data directory exists for local fallback
DATA_DIR.mkdir(parents=True, exist_ok=True)

if DATABASE_URL:
    # Use PostgreSQL (Production)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    engine = create_engine(SQLALCHEMY_DATABASE_URL)
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
    from src.models import Tenant, User, ChatSession, AccessRequest, ActivityLog, PendingTransfer

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
