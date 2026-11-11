"""
sso.py — Enterprise Single Sign-On (SSO), SAML 2.0, and OIDC API Endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Form, Request, status
from fastapi.responses import Response, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import hashlib
import re
import secrets
from datetime import datetime

from src.database import slugify, generate_join_code
from src.models import Tenant, User, TenantSSOConfig
from src.auth import create_user_token
from src.activity import log_activity
from src.config import SSO_ENABLED, SSO_ENTITY_ID, SSO_ACS_URL, SSO_FRONTEND_URL
from src.sso import (
    find_tenant_sso_by_email,
    RoleMappingEngine,
    generate_sp_metadata,
    generate_authn_request,
    parse_saml_response,
    generate_oidc_authorization_url,
    exchange_oidc_code,
    revoke_user_sessions,
    revoke_tenant_sessions,
)
from api.dependencies import get_db, get_current_user, get_current_admin_user
from api.limiter import limiter, get_ip_rate_limit_key, get_user_rate_limit_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["Enterprise SSO"])

# In-memory store for OIDC CSRF state validation fallback
_memory_oidc_states: Dict[str, int] = {}


class SSODiscoverResponse(BaseModel):
    sso_enabled: bool
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    idp_type: Optional[str] = None
    enforce_sso: bool = False
    login_url: Optional[str] = None
    message: Optional[str] = None


class OIDCCallbackRequest(BaseModel):
    code: str
    redirect_uri: str
    tenant_id: int
    state: Optional[str] = None


class RevocationRequest(BaseModel):
    user_id: Optional[int] = None
    tenant_id: Optional[int] = None
    all_tenants: bool = False
    reason: Optional[str] = None


@router.get("/discover", response_model=SSODiscoverResponse)
@limiter.limit("30/minute", key_func=get_ip_rate_limit_key)
def discover_sso(
    request: Request,
    email: str = Query(..., description="Corporate employee email address"),
    db: Session = Depends(get_db)
):
    """
    Auto-discovers the tenant organization and IdP provider for a corporate email address.
    Enables zero-friction enterprise logins (e.g. typing user@acme.com routes to Acme Okta/SAML).
    """
    if not email or "@" not in email or len(email.strip()) > 320:
        return SSODiscoverResponse(sso_enabled=False, message="Invalid employee email address format")

    if not SSO_ENABLED:
        return SSODiscoverResponse(sso_enabled=False, message="SSO is disabled on this platform")

    match = find_tenant_sso_by_email(email, db)
    if not match:
        return SSODiscoverResponse(sso_enabled=False, message="No enterprise organization matches this email domain")

    tenant, cfg = match
    if not cfg or not cfg.is_enabled:
        return SSODiscoverResponse(
            sso_enabled=False,
            tenant_id=tenant.id,
            tenant_name=tenant.name,
            message="SSO is not enabled for this organization"
        )

    # Determine login URL based on IdP type
    login_url = None
    if cfg.idp_type == "saml":
        login_url = f"/auth/sso/saml/login?tenant_id={tenant.id}&redirect=true"
    elif cfg.idp_type in ("oidc", "okta", "microsoft", "google"):
        login_url = f"/auth/sso/oidc/authorize?tenant_id={tenant.id}&redirect=true"

    return SSODiscoverResponse(
        sso_enabled=True,
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        idp_type=cfg.idp_type,
        enforce_sso=bool(cfg.enforce_sso),
        login_url=login_url,
    )


@router.get("/saml/metadata")
def get_sp_metadata():
    """Returns Service Provider (SP) XML metadata for importing into Okta, Azure AD, or Ping."""
    xml_data = generate_sp_metadata(entity_id=SSO_ENTITY_ID, acs_url=SSO_ACS_URL)
    return Response(content=xml_data, media_type="application/xml")


@router.get("/saml/login")
@limiter.limit("20/minute", key_func=get_ip_rate_limit_key)
def saml_login(
    request: Request,
    tenant_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """Initiates SAML AuthnRequest and returns redirection URL to IdP SingleSignOnService."""
    cfg = db.query(TenantSSOConfig).filter(
        TenantSSOConfig.tenant_id == tenant_id,
        TenantSSOConfig.is_enabled == True,
        TenantSSOConfig.idp_type == "saml"
    ).first()

    if not cfg or not cfg.idp_sso_url:
        raise HTTPException(
            status_code=400,
            detail=f"SAML 2.0 is not configured or enabled for tenant #{tenant_id}"
        )

    from src.sso.validators import validate_external_sso_url
    try:
        safe_idp_url = validate_external_sso_url(cfg.idp_sso_url, "IdP SSO URL")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    relay_state = f"tenant_{tenant_id}"
    redirect_url, request_id = generate_authn_request(
        idp_sso_url=safe_idp_url,
        sp_entity_id=SSO_ENTITY_ID,
        acs_url=SSO_ACS_URL,
        relay_state=relay_state
    )

    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header or request.query_params.get("redirect") == "true":
        return RedirectResponse(url=redirect_url, status_code=303)

    return {"redirect_url": redirect_url, "request_id": request_id}


def _enforce_sso_allowed_domain(email: str, cfg: TenantSSOConfig, tenant: Tenant) -> None:
    """Enforce corporate domain allowlist when configured on SSO config or tenant."""
    allowed_raw = (cfg.allowed_domains if cfg else None) or tenant.allowed_domains
    if not allowed_raw:
        return
    allowed_list = [d.strip().lower() for d in allowed_raw.split(",") if d.strip()]
    if not allowed_list:
        return
    domain = email.split("@")[-1].lower().strip().rstrip(".") if "@" in (email or "") else ""
    if domain not in allowed_list:
        raise HTTPException(
            status_code=403,
            detail=f"Email domain '@{domain}' is not authorized for '{tenant.name}' SSO."
        )


@router.post("/saml/acs")
@limiter.limit("30/minute", key_func=get_ip_rate_limit_key)
def saml_acs(
    request: Request,
    SAMLResponse: str = Form(...),
    RelayState: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    SAML Assertion Consumer Service (ACS) endpoint.
    Receives HTTP-POST from IdP, parses assertion, verifies signature, synchronizes
    directory groups to application roles, and logs in / provisions the enterprise user.
    """
    if not SSO_ENABLED:
        raise HTTPException(status_code=403, detail="Enterprise SSO is disabled on this platform.")

    # 1. Strictly resolve tenant_id from RelayState BEFORE trusting assertion claims
    tenant_id = None
    if RelayState:
        relay_match = re.search(r'(?:^|&)tenant_(\d+)(?:&|$)', RelayState.strip())
        if relay_match:
            tenant_id = int(relay_match.group(1))

    # 2. Resolve enabled SAML config & mandatory IdP X.509 certificate
    from src.sso.saml import extract_saml_issuer
    try:
        peeked_issuer = extract_saml_issuer(SAMLResponse)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"SAML authentication failed: {str(e)}")

    cfg = None
    if tenant_id:
        cfg = db.query(TenantSSOConfig).filter(
            TenantSSOConfig.tenant_id == tenant_id,
            TenantSSOConfig.is_enabled == True,
            TenantSSOConfig.idp_type == "saml",
        ).first()
    elif peeked_issuer:
        # IdP-initiated SAML lookup by Issuer EntityID (signature still verified strictly against cert)
        issuer_matches = db.query(TenantSSOConfig).filter(
            TenantSSOConfig.is_enabled == True,
            TenantSSOConfig.idp_type == "saml",
            TenantSSOConfig.idp_entity_id == peeked_issuer,
        ).all()
        if len(issuer_matches) == 1:
            cfg = issuer_matches[0]
            tenant_id = cfg.tenant_id

    if not tenant_id or not cfg or not cfg.idp_x509_cert or not cfg.idp_x509_cert.strip():
        logger.warning(f"SAML ACS rejected: tenant_id={tenant_id} has no enabled SAML IdP certificate configured.")
        raise HTTPException(
            status_code=400,
            detail="SAML SSO is not configured/enabled or missing IdP X.509 certificate for this organization."
        )

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or tenant.status == "suspended":
        raise HTTPException(status_code=403, detail="Organization is suspended or does not exist.")

    if cfg.idp_entity_id and peeked_issuer and peeked_issuer != cfg.idp_entity_id.strip():
        logger.warning(f"SAML Issuer mismatch for tenant #{tenant_id}: got '{peeked_issuer}', expected '{cfg.idp_entity_id}'")
        raise HTTPException(status_code=403, detail="SAML Issuer does not match organization IdP configuration.")

    # 3. Parse & cryptographically verify SAML assertion against registered IdP certificate
    try:
        profile = parse_saml_response(SAMLResponse, expected_recipient=SSO_ENTITY_ID, idp_cert_pem=cfg.idp_x509_cert)
    except Exception as e:
        logger.error(f"SAML assertion validation failed: {e}")
        raise HTTPException(status_code=400, detail=f"SAML authentication failed: {str(e)}")

    # 3.1 Mandatory SAML Assertion Replay Protection (CWE-294)
    from src.sso.revocation import check_and_record_assertion_id
    replay_id = getattr(profile, "assertion_id", None) or f"sha256_{hashlib.sha256(SAMLResponse.encode('utf-8')).hexdigest()}"
    if not check_and_record_assertion_id(replay_id):
        logger.warning(f"SAML replay attack blocked for assertion_id={replay_id}")
        raise HTTPException(status_code=400, detail="SAML assertion has already been processed (replay detected).")

    # 4. Resolve application role from Directory Groups
    resolved_role = RoleMappingEngine.resolve_role(profile.groups, cfg.role_mapping_json, cfg.default_role or "user")

    # 5. Provision or Update User (cross-tenant check precedes domain allowlist)
    user = db.query(User).filter(
        (func.lower(User.email) == profile.email.lower()) |
        ((User.tenant_id == tenant.id) & (User.auth_provider == "saml") & (User.oauth_id == profile.oauth_id))
    ).first()

    if user:
        # Cross-Tenant Security Boundary Check
        if user.tenant_id != tenant.id and not user.is_platform_admin:
            logger.warning(
                f"Cross-tenant SAML login blocked: user '{user.username}' (tenant #{user.tenant_id}) "
                f"attempted auth via tenant #{tenant.id} IdP"
            )
            raise HTTPException(
                status_code=403,
                detail="Security violation: User account belongs to another organization."
            )

        _enforce_sso_allowed_domain(profile.email, cfg, tenant)

        # Check suspended tenant
        if user.tenant and user.tenant.status == "suspended" and not user.is_platform_admin:
            raise HTTPException(status_code=403, detail="Organization is suspended.")

        # Update role based on IdP directory groups if user is not tenant owner
        if user.role != "superadmin":
            user.role = resolved_role

        user.auth_provider = "saml"
        user.oauth_id = profile.oauth_id
        db.commit()
        db.refresh(user)

        log_activity(
            tenant_id=user.tenant_id or tenant.id,
            user_id=user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=f"User '{user.username}' signed in via SAML 2.0 (role={user.role})"
        )
    else:
        _enforce_sso_allowed_domain(profile.email, cfg, tenant)
        # Generate clean unique username
        base_user = re.sub(r'[^a-zA-Z0-9_]', '', profile.name.lower().replace(" ", "_")).strip()
        if not base_user or len(base_user) < 3:
            base_user = profile.email.split("@")[0].lower()
        base_user = re.sub(r'[^a-zA-Z0-9_]', '', base_user)[:20]

        unique_username = base_user
        counter = 1
        while db.query(User).filter(User.username == unique_username).first():
            unique_username = f"{base_user}_{counter}"
            counter += 1

        # Synchronize PostgreSQL auto-increment sequence before insertion
        from src.database import engine
        from sqlalchemy import text
        if engine.dialect.name == "postgresql":
            try:
                db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
            except Exception as seq_err:
                logger.warning(f"SAML sequence sync notice: {seq_err}")

        user = User(
            username=unique_username,
            email=profile.email,
            auth_provider="saml",
            oauth_id=profile.oauth_id,
            role=resolved_role,
            tenant_id=tenant.id,
            is_platform_admin=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        log_activity(
            tenant_id=tenant.id,
            user_id=user.id,
            action="USER_REGISTER",
            category="AUTH",
            description=f"User '{user.username}' provisioned via SAML 2.0 in '{tenant.name}' (role={resolved_role})"
        )

    # Issue Enterprise JWT Token
    token = create_user_token(user)

    # Safe return_to parameter extracted from RelayState (Strict Open Redirect Prevention)
    safe_return_to = None
    if RelayState:
        for part in RelayState.split("&"):
            if part.startswith("return_to="):
                candidate = part.split("return_to=")[-1].strip()
                if candidate.startswith("/") and not candidate.startswith("//") and "\\" not in candidate:
                    safe_return_to = candidate

    # If browser submitted directly via form, redirect to frontend callback
    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header or "application/xhtml+xml" in accept_header:
        from urllib.parse import urlencode
        params = {
            "token": token,
            "role": user.role,
            "tenant_id": str(user.tenant_id),
            "username": user.username,
            "tenant_name": tenant.name,
            "email": user.email or "",
            "is_platform_admin": "true" if user.is_platform_admin else "false",
        }
        if safe_return_to:
            params["return_to"] = safe_return_to
        redirect_target = f"{SSO_FRONTEND_URL}/auth/callback#{urlencode(params)}"
        return RedirectResponse(url=redirect_target, status_code=303)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name,
        "is_platform_admin": bool(user.is_platform_admin),
        "username": user.username,
        "email": user.email,
        "return_to": safe_return_to,
    }


@router.get("/oidc/authorize")
@limiter.limit("20/minute", key_func=get_ip_rate_limit_key)
def oidc_authorize(
    request: Request,
    tenant_id: int = Query(...),
    redirect_uri: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Generates the OIDC authorization URL for an organization's configured IdP."""
    cfg = db.query(TenantSSOConfig).filter(
        TenantSSOConfig.tenant_id == tenant_id,
        TenantSSOConfig.is_enabled == True,
    ).first()

    if not cfg or not cfg.oidc_issuer_url or not cfg.oidc_client_id:
        raise HTTPException(
            status_code=400,
            detail=f"Enterprise OIDC is not configured or enabled for tenant #{tenant_id}"
        )

    eff_redirect = redirect_uri or f"{SSO_FRONTEND_URL}/auth/callback"
    nonce = secrets.token_urlsafe(16)
    state = f"oidc_{tenant_id}_{nonce}"

    # Cache CSRF state token in Redis with 15m TTL (with in-memory fallback)
    from src.sso.revocation import get_redis_client
    r = get_redis_client()
    if r:
        try:
            r.set(f"sso:oidc:state:{state}", str(tenant_id), ex=900)
        except Exception as se:
            logger.warning(f"OIDC state Redis cache notice: {se}")
    _memory_oidc_states[state] = tenant_id

    try:
        auth_url = generate_oidc_authorization_url(
            issuer_url=cfg.oidc_issuer_url,
            client_id=cfg.oidc_client_id,
            redirect_uri=eff_redirect,
            state=state,
            scopes=cfg.oidc_scopes or "openid email profile groups"
        )
    except ValueError as url_err:
        raise HTTPException(status_code=400, detail=str(url_err))

    accept_header = request.headers.get("accept", "")
    if "text/html" in accept_header or request.query_params.get("redirect") == "true":
        return RedirectResponse(url=auth_url, status_code=303)

    return {"redirect_url": auth_url, "state": state}


@router.post("/oidc/callback")
@limiter.limit("30/minute", key_func=get_ip_rate_limit_key)
def oidc_callback(
    request: Request,
    payload: OIDCCallbackRequest,
    db: Session = Depends(get_db)
):
    """Exchanges OIDC code for token, verifies claims, maps directory groups, and returns JWT."""
    # CSRF State Validation
    if not payload.state:
        logger.warning("OIDC callback rejected: missing CSRF state parameter.")
        raise HTTPException(
            status_code=400,
            detail="OIDC state parameter is required for CSRF protection."
        )

    from src.sso.revocation import get_redis_client
    r = get_redis_client()
    expected_tenant = None
    if r:
        try:
            expected_tenant = r.get(f"sso:oidc:state:{payload.state}")
            if expected_tenant:
                r.delete(f"sso:oidc:state:{payload.state}")
        except Exception:
            pass
    if not expected_tenant and payload.state in _memory_oidc_states:
        expected_tenant = str(_memory_oidc_states.pop(payload.state, None))

    if not expected_tenant or int(expected_tenant) != payload.tenant_id:
        logger.warning(f"OIDC CSRF state mismatch or invalid: state={payload.state}, expected tenant={expected_tenant}, got #{payload.tenant_id}")
        raise HTTPException(
            status_code=400,
            detail="OIDC state validation failed: invalid, expired, or tenant mismatch (possible CSRF attack)."
        )

    if not SSO_ENABLED:
        raise HTTPException(status_code=403, detail="Enterprise SSO is disabled on this platform.")

    cfg = db.query(TenantSSOConfig).filter(
        TenantSSOConfig.tenant_id == payload.tenant_id,
        TenantSSOConfig.is_enabled == True,
        TenantSSOConfig.idp_type.in_(["oidc", "okta", "microsoft", "google"]),
    ).first()

    if not cfg or not cfg.oidc_issuer_url or not cfg.oidc_client_id or not cfg.oidc_client_secret:
        raise HTTPException(
            status_code=400,
            detail=f"Enterprise OIDC credentials missing for tenant #{payload.tenant_id}"
        )

    tenant = db.query(Tenant).filter(Tenant.id == payload.tenant_id).first()
    if not tenant or tenant.status == "suspended":
        raise HTTPException(status_code=403, detail="Organization is suspended or does not exist.")

    try:
        profile = exchange_oidc_code(
            issuer_url=cfg.oidc_issuer_url,
            client_id=cfg.oidc_client_id,
            client_secret=cfg.oidc_client_secret,
            code=payload.code,
            redirect_uri=payload.redirect_uri
        )
    except Exception as e:
        logger.error(f"OIDC exchange failed: {e}")
        raise HTTPException(status_code=400, detail=f"OIDC verification failed: {str(e)}")

    # Resolve application role from Directory Groups
    resolved_role = RoleMappingEngine.resolve_role(
        profile.groups, cfg.role_mapping_json, cfg.default_role or "user"
    )

    user = db.query(User).filter(
        (func.lower(User.email) == profile.email.lower()) |
        ((User.tenant_id == tenant.id) & (User.auth_provider == "oidc") & (User.oauth_id == profile.oauth_id))
    ).first()

    if user:
        # Cross-Tenant Security Boundary Check
        if user.tenant_id != tenant.id and not user.is_platform_admin:
            logger.warning(
                f"Cross-tenant OIDC login blocked: user '{user.username}' (tenant #{user.tenant_id}) "
                f"attempted auth via tenant #{tenant.id} IdP"
            )
            raise HTTPException(
                status_code=403,
                detail="Security violation: User account belongs to another organization."
            )

        _enforce_sso_allowed_domain(profile.email, cfg, tenant)

        # Check suspended tenant
        if user.tenant and user.tenant.status == "suspended" and not user.is_platform_admin:
            raise HTTPException(status_code=403, detail="Organization is suspended.")

        if user.role != "superadmin":
            user.role = resolved_role
        user.auth_provider = "oidc"
        user.oauth_id = profile.oauth_id
        if profile.avatar_url and not user.avatar_url:
            user.avatar_url = profile.avatar_url
        db.commit()
        db.refresh(user)

        log_activity(
            tenant_id=user.tenant_id or tenant.id,
            user_id=user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=f"User '{user.username}' signed in via Enterprise OIDC (role={user.role})"
        )
    else:
        _enforce_sso_allowed_domain(profile.email, cfg, tenant)
        base_user = re.sub(r'[^a-zA-Z0-9_]', '', profile.name.lower().replace(" ", "_")).strip()
        if not base_user or len(base_user) < 3:
            base_user = profile.email.split("@")[0].lower()
        base_user = re.sub(r'[^a-zA-Z0-9_]', '', base_user)[:20]

        unique_username = base_user
        counter = 1
        while db.query(User).filter(User.username == unique_username).first():
            unique_username = f"{base_user}_{counter}"
            counter += 1

        # Synchronize PostgreSQL auto-increment sequence before insertion
        from src.database import engine
        from sqlalchemy import text
        if engine.dialect.name == "postgresql":
            try:
                db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
            except Exception as seq_err:
                logger.warning(f"OIDC sequence sync notice: {seq_err}")

        user = User(
            username=unique_username,
            email=profile.email,
            auth_provider="oidc",
            oauth_id=profile.oauth_id,
            role=resolved_role,
            tenant_id=tenant.id,
            is_platform_admin=False,
            avatar_url=profile.avatar_url,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        log_activity(
            tenant_id=tenant.id,
            user_id=user.id,
            action="USER_REGISTER",
            category="AUTH",
            description=f"User '{user.username}' provisioned via Enterprise OIDC in '{tenant.name}' (role={resolved_role})"
        )

    token = create_user_token(user)

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant.name,
        "is_platform_admin": bool(user.is_platform_admin),
        "username": user.username,
        "email": user.email,
        "avatar_url": user.avatar_url,
    }


@router.post("/revoke")
@limiter.limit("15/minute", key_func=get_user_rate_limit_key)
def revoke_sessions(
    request: Request,
    payload: RevocationRequest,
    current_user: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    Enterprise Session Revocation Webhook.
    Immediately invalidates active JWT sessions for a user or tenant across all workers.
    """
    if payload.all_tenants:
        if not current_user.is_platform_admin:
            raise HTTPException(status_code=403, detail="Platform admin privileges required for global revocation.")
        tenants = db.query(Tenant).all()
        for t in tenants:
            revoke_tenant_sessions(t.id)
        log_activity(
            tenant_id=current_user.tenant_id or 1,
            user_id=current_user.id,
            action="SESSION_REVOKED",
            category="AUTH",
            description="Revoked all enterprise sessions globally across all tenants",
            details={"all_tenants": True, "reason": payload.reason}
        )
        return {"status": "success", "message": "All enterprise sessions globally revoked."}

    target_user_id = payload.user_id
    target_tenant_id = payload.tenant_id

    # Require explicit revocation target to prevent accidental organization-wide logout
    if target_user_id is None and target_tenant_id is None:
        raise HTTPException(
            status_code=400,
            detail="Explicit revocation target required: specify 'user_id', 'tenant_id', or 'all_tenants=True'."
        )

    # Tenant admins can only revoke sessions within their own tenant
    if not current_user.is_platform_admin:
        if target_tenant_id and target_tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Cannot revoke sessions for another organization.")
        if target_user_id:
            target_user = db.query(User).filter(User.id == target_user_id).first()
            if not target_user or target_user.tenant_id != current_user.tenant_id:
                raise HTTPException(status_code=403, detail="Target user not found in your organization.")

    if target_user_id:
        revoke_user_sessions(target_user_id)
        log_activity(
            tenant_id=current_user.tenant_id or 1,
            user_id=current_user.id,
            action="SESSION_REVOKED",
            category="AUTH",
            description=f"Revoked all sessions for user_id={target_user_id}",
            details={"target_user_id": target_user_id, "reason": payload.reason}
        )

    if target_tenant_id:
        revoke_tenant_sessions(target_tenant_id)
        log_activity(
            tenant_id=target_tenant_id,
            user_id=current_user.id,
            action="SESSION_REVOKED",
            category="AUTH",
            description=f"Revoked all sessions for tenant_id={target_tenant_id}",
            details={"target_tenant_id": target_tenant_id, "reason": payload.reason}
        )

    return {"status": "success", "message": "Sessions revoked successfully."}
