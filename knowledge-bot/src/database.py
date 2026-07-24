import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import DATA_DIR

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

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
