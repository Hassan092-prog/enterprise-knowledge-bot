from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from src.database import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)
    status = Column(String, default="active")  # 'active', 'suspended'
    join_code = Column(String, nullable=True)   # Join code for controlled onboarding
    superadmin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL", use_alter=True, name="fk_tenant_superadmin_user_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="tenant", foreign_keys="User.tenant_id", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="tenant", cascade="all, delete-orphan")
    transfers = relationship("PendingTransfer", back_populates="tenant", cascade="all, delete-orphan")
    access_requests = relationship("AccessRequest", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")  # 'superadmin', 'admin', 'editor', 'user'
    is_platform_admin = Column(Boolean, default=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="users", foreign_keys=[tenant_id])
    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String, default="New Chat")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role = Column(String)  # 'user' or 'assistant'
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")


class AccessRequest(Base):
    __tablename__ = "access_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    requested_role = Column(String, nullable=False)  # 'editor' or 'admin'
    status = Column(String, default="pending")        # 'pending', 'approved', 'rejected'
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    tenant = relationship("Tenant", back_populates="access_requests")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String, nullable=False)       # "USER_LOGIN", "DOC_UPLOAD", "QUERY_EXECUTED", etc.
    category = Column(String, nullable=False)     # "AUTH", "GOVERNANCE", "KNOWLEDGE", "QUERY"
    description = Column(Text, nullable=False)
    details = Column(Text, nullable=True)         # JSON metadata
    timestamp = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_activity_tenant_time", "tenant_id", "timestamp"),
        Index("ix_activity_category", "tenant_id", "category"),
    )

    tenant = relationship("Tenant", back_populates="activity_logs")
    user = relationship("User")


class PendingTransfer(Base):
    __tablename__ = "pending_transfers"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="pending")  # 'pending', 'accepted', 'expired', 'cancelled'
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)                # created_at + 24 hours

    tenant = relationship("Tenant", back_populates="transfers")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])
