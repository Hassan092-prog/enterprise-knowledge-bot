import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import DATA_DIR, DATABASE_URL

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
