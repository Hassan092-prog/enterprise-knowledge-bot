"""
__init__.py — Enterprise Single Sign-On (SSO) & SAML / OIDC Subsystem.
"""

from typing import Optional, Tuple
from sqlalchemy.orm import Session

from src.sso.base import SSOUserProfile, RoleMappingEngine
from src.sso.revocation import (
    revoke_user_sessions,
    revoke_tenant_sessions,
    blacklist_token,
    is_session_revoked,
    is_token_blacklisted,
)
from src.sso.saml import (
    generate_sp_metadata,
    generate_authn_request,
    parse_saml_response,
    parse_idp_metadata_xml,
)
from src.sso.oidc import (
    discover_oidc_endpoints,
    generate_oidc_authorization_url,
    exchange_oidc_code,
)
from src.models import Tenant, TenantSSOConfig


PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "mail.com", "proton.me", "protonmail.com",
    "aol.com", "zoho.com", "gmx.com", "yandex.com",
}


def find_tenant_sso_by_email(email: str, db: Session) -> Optional[Tuple[Tenant, Optional[TenantSSOConfig]]]:
    """
    Given an employee email (e.g. alice@acme.com), resolves the tenant organization
    and their active SSO configuration if configured.
    """
    if not email or "@" not in email:
        return None

    domain = email.split("@")[-1].lower().strip().rstrip(".")
    if domain in PUBLIC_EMAIL_DOMAINS:
        return None

    # 1. Search TenantSSOConfig allowed_domains
    configs = db.query(TenantSSOConfig).filter(TenantSSOConfig.is_enabled == True).all()
    for cfg in configs:
        if cfg.allowed_domains:
            domains = [d.strip().lower() for d in cfg.allowed_domains.split(",") if d.strip()]
            if domain in domains:
                tenant = db.query(Tenant).filter(Tenant.id == cfg.tenant_id, Tenant.status == "active").first()
                if tenant:
                    return tenant, cfg

    # 2. Search Tenant allowed_domains fallback
    tenants = db.query(Tenant).filter(Tenant.status == "active").all()
    for t in tenants:
        if t.allowed_domains:
            domains = [d.strip().lower() for d in t.allowed_domains.split(",") if d.strip()]
            if domain in domains:
                cfg = db.query(TenantSSOConfig).filter(TenantSSOConfig.tenant_id == t.id).first()
                return t, cfg

    return None

