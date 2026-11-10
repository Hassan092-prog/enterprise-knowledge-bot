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
    allowed_domains = Column(String, nullable=True)  # Comma-separated corporate domains, e.g. "acme.com,acmewidgets.com"
    monthly_token_budget = Column(Integer, default=500_000)   # Token cap per month
    current_month_tokens = Column(Integer, default=0)         # Running total
    budget_reset_at = Column(DateTime, nullable=True)         # Timestamp when month was last reset
    superadmin_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL", use_alter=True, name="fk_tenant_superadmin_user_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="tenant", foreign_keys="User.tenant_id", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="tenant", cascade="all, delete-orphan")
    transfers = relationship("PendingTransfer", back_populates="tenant", cascade="all, delete-orphan")
    access_requests = relationship("AccessRequest", back_populates="tenant", cascade="all, delete-orphan")
    sso_config = relationship("TenantSSOConfig", back_populates="tenant", uselist=False, cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)  # Nullable for OAuth-only accounts
    role = Column(String, default="user")  # 'superadmin', 'admin', 'editor', 'user'
    auth_provider = Column(String, default="local")  # 'local', 'google', 'github', 'microsoft'
    oauth_id = Column(String, index=True, nullable=True)  # Provider's unique subject ID
    avatar_url = Column(String, nullable=True)
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
    sources_json = Column(Text, nullable=True)  # JSON-encoded array of retrieved source citations
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


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)      # Canonical / normalized ID (e.g. "acme_corporation")
    name = Column(String, nullable=False)                       # Display label (e.g. "Acme Corporation")
    entity_type = Column(String, nullable=False, index=True)    # ORGANIZATION, SYSTEM, POLICY, INCIDENT, DEPARTMENT, METRIC, PERSON
    description = Column(Text, nullable=True)
    source_documents = Column(Text, nullable=True)              # JSON-encoded list of source filenames
    properties_json = Column(Text, nullable=True)               # Extra attributes/metadata in JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_node_tenant_entity", "tenant_id", "entity_id", unique=True),
    )


class KnowledgeEdge(Base):
    __tablename__ = "knowledge_edges"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_entity_id = Column(String, nullable=False, index=True)
    target_entity_id = Column(String, nullable=False, index=True)
    relation_type = Column(String, nullable=False, index=True)  # AFFECTS, GOVERNED_BY, RESPONSIBLE_FOR, DEPLOYED_ON, etc.
    weight = Column(Integer, default=1)
    context_snippet = Column(Text, nullable=True)
    source_document = Column(String, nullable=True, index=True)
    properties_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_edge_tenant_source_target", "tenant_id", "source_entity_id", "target_entity_id", "relation_type"),
    )


class TenantSSOConfig(Base):
    __tablename__ = "tenant_sso_configs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    idp_type = Column(String(32), default="oidc")  # 'oidc', 'saml', 'okta', 'google', 'microsoft'
    is_enabled = Column(Boolean, default=True)
    enforce_sso = Column(Boolean, default=False)   # If True, password login disabled for users with tenant domain

    # SAML 2.0 Configuration
    idp_entity_id = Column(String(512), nullable=True)  # IdP Issuer / EntityID
    idp_sso_url = Column(String(1024), nullable=True)   # IdP SingleSignOnService URL
    idp_x509_cert = Column(Text, nullable=True)         # Public X.509 certificate PEM for signature verification
    idp_metadata_xml = Column(Text, nullable=True)      # Raw uploaded IdP metadata XML

    # Enterprise OIDC Configuration (Okta, Entra ID, PingFederate, Keycloak)
    oidc_issuer_url = Column(String(1024), nullable=True) # e.g. https://company.okta.com
    oidc_client_id = Column(String(256), nullable=True)
    oidc_client_secret = Column(String(512), nullable=True)
    oidc_scopes = Column(String(256), default="openid email profile groups")

    # Domain Restriction & Role Sync
    allowed_domains = Column(String(512), nullable=True) # e.g. "company.com, company-intl.com"
    default_role = Column(String(32), default="user")    # 'user', 'editor', 'admin'
    role_mapping_json = Column(Text, nullable=True)      # JSON mapping: e.g. {"IT-Admins": "admin", "Editors": "editor"}

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tenant = relationship("Tenant", back_populates="sso_config")
