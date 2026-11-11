from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging
import secrets
import threading
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from src.models import User, AccessRequest, Tenant, TenantSSOConfig
from api.dependencies import get_db, get_current_user
from src.auth import verify_password, get_password_hash, create_user_token
from src.activity import log_activity
from api.limiter import limiter, get_ip_rate_limit_key, get_user_rate_limit_key

logger = logging.getLogger(__name__)
router = APIRouter()

class UserCreate(BaseModel):
    username: str
    password: str
    company_name: Optional[str] = None
    join_code: Optional[str] = None

class RoleRequest(BaseModel):
    role: str

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str
    tenant_id: Optional[int] = None
    tenant_name: Optional[str] = None
    is_platform_admin: bool = False
    username: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None

class OAuthCallbackRequest(BaseModel):
    code: str
    redirect_uri: str
    state: Optional[str] = None
    company_name: Optional[str] = None
    join_code: Optional[str] = None

from cachetools import TTLCache

_oauth_state_lock = threading.Lock()
_memory_oauth_states: TTLCache = TTLCache(maxsize=500, ttl=900)  # H-3/H-11 fix: bounded TTL eviction & lock, no unbounded growth

class TenantDomainUpdate(BaseModel):
    allowed_domains: str

PUBLIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com",
    "outlook.com", "hotmail.com", "live.com", "msn.com",
    "icloud.com", "me.com", "mac.com",
    "mail.com", "proton.me", "protonmail.com",
    "aol.com", "zoho.com", "gmx.com", "yandex.com",
}

@router.post("/register", response_model=Token)
@limiter.limit("5/minute", key_func=get_ip_rate_limit_key)
def register(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
    try:
        # Synchronize postgres auto-increment sequences before insertions
        from src.database import slugify, generate_join_code, engine
        from sqlalchemy import text
        if engine.dialect.name == "postgresql":
            try:
                db.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
                db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
            except Exception as seq_err:
                logger.warning(f"Registration sequence sync notice: {seq_err}")

        clean_username = (user_data.username or "").strip()
        if len(clean_username) < 3 or len(user_data.password or "") < 8:
            raise HTTPException(
                status_code=400,
                detail="Username must be at least 3 characters and password must be at least 8 characters.",
            )
        db_user = db.query(User).filter(User.username == clean_username).first()
        if db_user:
            raise HTTPException(status_code=400, detail="Username already registered")
        
        tenant = None
        assigned_role = "user"
        if user_data.company_name and user_data.company_name.strip():
            company_clean = user_data.company_name.strip()
            slug = slugify(company_clean)
            tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
            if tenant is None:
                tenant = Tenant(
                    name=company_clean,
                    slug=slug,
                    status="active",
                    join_code=generate_join_code(),
                    monthly_token_budget=500000,
                    current_month_tokens=0,
                    budget_reset_at=datetime.utcnow()
                )
                db.add(tenant)
                db.flush()
                assigned_role = "superadmin"
            else:
                if tenant.status == "suspended":
                    raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
                # Existing company requires valid join code
                if not user_data.join_code or user_data.join_code.strip() != (tenant.join_code or "").strip():
                    raise HTTPException(status_code=403, detail="Invalid or missing join code for this organization")
                assigned_role = "user"
        else:
            # Default tenant fallback
            tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()
            if tenant and tenant.status == "suspended":
                raise HTTPException(status_code=403, detail="Default organization is suspended.")

        hashed_password = get_password_hash(user_data.password)
        new_user = User(
            username=user_data.username.strip(),
            hashed_password=hashed_password,
            role=assigned_role,
            tenant_id=tenant.id if tenant else None,
            is_platform_admin=False
        )
        db.add(new_user)
        db.flush()

        if tenant and assigned_role == "superadmin" and tenant.superadmin_user_id is None:
            tenant.superadmin_user_id = new_user.id

        db.commit()
        db.refresh(new_user)

        if tenant:
            log_activity(
                tenant_id=tenant.id,
                user_id=new_user.id,
                action="USER_REGISTER",
                category="AUTH",
                description=f"User '{new_user.username}' registered as '{assigned_role}' in '{tenant.name}'"
            )

        access_token = create_user_token(new_user)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": new_user.role,
            "tenant_id": new_user.tenant_id,
            "tenant_name": tenant.name if tenant else None,
            "is_platform_admin": bool(new_user.is_platform_admin)
        }
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as ie:
        db.rollback()
        logger.warning(f"Registration conflict (L-4 atomic race guard): {ie}")
        raise HTTPException(
            status_code=409,
            detail="Username or organization name is already taken. If joining an existing organization, please provide its join code."
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Registration error: {e}")
        from src.config import ENVIRONMENT
        safe_detail = "Registration failed. Please try again." if ENVIRONMENT == "production" else f"Registration failed: {str(e)}"
        raise HTTPException(status_code=400, detail=safe_detail)

@router.post("/login", response_model=Token)
@limiter.limit("10/minute", key_func=get_ip_rate_limit_key)
def login(request: Request, user_data: UserCreate, db: Session = Depends(get_db)):
    clean_username = (user_data.username or "").strip()
    user = db.query(User).filter(User.username == clean_username).first()
    if not user or not user.hashed_password or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Ensure tenant_id is populated
    if user.tenant_id is None:
        default_tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()
        if default_tenant:
            user.tenant_id = default_tenant.id
            db.commit()
            db.refresh(user)

    # Block login if organization is suspended (unless platform admin)
    if user.tenant and user.tenant.status == "suspended" and not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization has been suspended. Please contact platform administrator.",
        )

    # Check if SSO is enforced for this tenant (Phase 12 Enterprise SSO)
    # Organization SuperAdmins and Platform Admins retain break-glass password login
    # access to prevent lockout during IdP outages or certificate expirations.
    is_break_glass = False
    if user.tenant_id:
        from src.models import TenantSSOConfig
        sso_cfg = db.query(TenantSSOConfig).filter(
            TenantSSOConfig.tenant_id == user.tenant_id,
            TenantSSOConfig.is_enabled == True,
            TenantSSOConfig.enforce_sso == True
        ).first()
        if sso_cfg:
            if not user.is_platform_admin and user.role != "superadmin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Single Sign-On (SSO) is enforced for your organization. Please sign in via your corporate Identity Provider."
                )
            is_break_glass = True

    tenant_name = user.tenant.name if user.tenant else None

    # Log successful login
    if user.tenant_id:
        login_desc = (
            f"User '{user.username}' logged in via password (SSO break-glass access)"
            if is_break_glass
            else f"User '{user.username}' logged in"
        )
        log_activity(
            tenant_id=user.tenant_id,
            user_id=user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=login_desc
        )

    access_token = create_user_token(user)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "tenant_id": user.tenant_id,
        "tenant_name": tenant_name,
        "is_platform_admin": bool(user.is_platform_admin),
        "username": user.username,
        "email": getattr(user, "email", None),
        "avatar_url": getattr(user, "avatar_url", None)
    }

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    # H-2 fix: Removed token re-issue from /me response — prevents JWT revocation bypass.
    # Fresh tokens are only issued at login/OAuth/SSO/register endpoints.
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": getattr(current_user, "email", None),
        "avatar_url": getattr(current_user, "avatar_url", None),
        "auth_provider": getattr(current_user, "auth_provider", "local"),
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "tenant_name": current_user.tenant.name if current_user.tenant else None,
        "tenant_slug": current_user.tenant.slug if current_user.tenant else None,
        "allowed_domains": current_user.tenant.allowed_domains if current_user.tenant else None,
        "is_platform_admin": bool(current_user.is_platform_admin),
    }

@router.post("/request_role")
def request_role(role_req: RoleRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if role_req.role not in ["editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role requested")
    
    # Check if already requested in this tenant
    existing = db.query(AccessRequest).filter(
        AccessRequest.user_id == current_user.id,
        AccessRequest.tenant_id == current_user.tenant_id,
        AccessRequest.status == "pending"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending role request")
        
    req = AccessRequest(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        requested_role=role_req.role
    )
    db.add(req)
    db.commit()

    if current_user.tenant_id:
        log_activity(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="ROLE_REQUEST",
            category="GOVERNANCE",
            description=f"User '{current_user.username}' requested promotion to '{role_req.role}'"
        )

    return {"status": "success"}

@router.get("/my_request")
def my_request(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    req = db.query(AccessRequest).filter(
        AccessRequest.user_id == current_user.id,
        AccessRequest.tenant_id == current_user.tenant_id
    ).order_by(AccessRequest.created_at.desc()).first()
    if req:
        return {"requested_role": req.requested_role, "status": req.status}
    return None


# ──────────────────────────────────────────────────────────────────
# ENTERPRISE OAUTH2 & DOMAIN AUTO-ROUTING (PILLAR 8)
# ──────────────────────────────────────────────────────────────────

@router.get("/oauth/providers")
def get_oauth_providers():
    """Returns the availability status of OAuth2 providers."""
    from src.oauth import get_available_oauth_providers
    return get_available_oauth_providers()

@router.get("/oauth/{provider}/authorize")
@limiter.limit("30/minute", key_func=get_ip_rate_limit_key)
def oauth_authorize(request: Request, provider: str, redirect_uri: str):
    """Generates the provider authorization URL with a single-use CSRF state token."""
    from src.oauth import generate_oauth_authorization_url
    from src.sso.revocation import get_redis_client
    try:
        clean_provider = (provider or "").lower().strip()
        url = generate_oauth_authorization_url(provider=clean_provider, redirect_uri=redirect_uri)

        nonce_state = f"oauth_{clean_provider}_{secrets.token_urlsafe(16)}"
        parsed = urlparse(url)
        query_params = [(k, v) for k, v in parse_qsl(parsed.query) if k != "state"]
        query_params.append(("state", nonce_state))
        final_url = urlunparse(parsed._replace(query=urlencode(query_params)))

        r = get_redis_client()
        if r:
            try:
                r.set(f"oauth:state:{nonce_state}", clean_provider, ex=900)
            except Exception as se:
                logger.warning(f"OAuth state Redis cache notice: {se}")
        with _oauth_state_lock:
            _memory_oauth_states[nonce_state] = clean_provider

        return {"authorization_url": final_url, "state": nonce_state}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

def _validate_and_consume_oauth_state(provider: str, state: Optional[str]) -> None:
    """Validate and consume single-use OAuth CSRF state against Redis / in-memory fallback."""
    if not state:
        raise HTTPException(
            status_code=400,
            detail="OAuth state parameter is required for CSRF protection.",
        )
    from src.sso.revocation import get_redis_client
    clean_provider = (provider or "").lower().strip()
    expected_provider = None
    r = get_redis_client()
    if r:
        try:
            expected_provider = r.get(f"oauth:state:{state}")
            if expected_provider:
                r.delete(f"oauth:state:{state}")
        except Exception:
            pass
    if not expected_provider:
        with _oauth_state_lock:
            if state in _memory_oauth_states:
                expected_provider = _memory_oauth_states.pop(state, None)

    if isinstance(expected_provider, bytes):
        expected_provider = expected_provider.decode("utf-8", errors="ignore")

    if not expected_provider or expected_provider != clean_provider:
        raise HTTPException(
            status_code=400,
            detail="OAuth state validation failed: invalid, expired, or provider mismatch (possible CSRF attack).",
        )


def _enforce_oauth_sso_gate(db: Session, tenant_id: Optional[int], provider: str, user_role: str = "user", is_platform_admin: bool = False) -> None:
    """Block social OAuth login/provisioning when an organization enforces an enterprise IdP (e.g. SAML/Okta)."""
    if not tenant_id:
        return
    sso_cfg = db.query(TenantSSOConfig).filter(
        TenantSSOConfig.tenant_id == tenant_id,
        TenantSSOConfig.is_enabled == True,
        TenantSSOConfig.enforce_sso == True,
    ).first()
    if sso_cfg and (sso_cfg.idp_type or "").lower() != provider.lower():
        if not is_platform_admin and user_role != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Single Sign-On (SSO) is enforced for this organization. Please sign in via your corporate Identity Provider.",
            )


def _is_domain_claimed(db: Session, domain: str) -> bool:
    """Return True if a corporate domain is already claimed by any Tenant or TenantSSOConfig."""
    d_low = domain.lower().strip()
    for t in db.query(Tenant).all():
        if t.allowed_domains:
            claimed = [x.strip().lower() for x in t.allowed_domains.split(",") if x.strip()]
            if d_low in claimed:
                return True
    for cfg in db.query(TenantSSOConfig).all():
        if cfg.allowed_domains:
            claimed = [x.strip().lower() for x in cfg.allowed_domains.split(",") if x.strip()]
            if d_low in claimed:
                return True
    return False


@router.post("/oauth/{provider}/callback", response_model=Token)
@limiter.limit("20/minute", key_func=get_ip_rate_limit_key)
def oauth_callback(request: Request, provider: str, request_body: OAuthCallbackRequest, db: Session = Depends(get_db)):
    """
    Exchanges code for verified identity, matches corporate domain or provisions account,
    and returns enterprise multi-tenant JWT token.
    """
    from src.oauth import exchange_oauth_code
    from src.database import slugify, generate_join_code
    from src.sso import find_tenant_sso_by_email
    import re

    _validate_and_consume_oauth_state(provider=provider, state=request_body.state)

    try:
        profile = exchange_oauth_code(
            provider=provider,
            code=request_body.code,
            redirect_uri=request_body.redirect_uri
        )
    except Exception as e:
        logger.error(f"OAuth code exchange failed: {e}")
        # M-9 fix: Never expose raw OAuth provider exception details to callers in production
        from src.config import ENVIRONMENT
        safe_detail = "OAuth verification failed. Please try again." if ENVIRONMENT == "production" else f"OAuth verification failed: {str(e)}"
        raise HTTPException(status_code=400, detail=safe_detail)

    email = (profile.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Identity provider did not return a verified email address.")
    oauth_id = profile.get("oauth_id")
    name = profile.get("name") or "User"
    avatar_url = profile.get("avatar_url")

    # 1. Check if user already exists by email (case-insensitive) or provider sub
    existing_user = db.query(User).filter(
        (func.lower(User.email) == email.lower()) |
        ((User.auth_provider == provider) & (User.oauth_id == oauth_id))
    ).first()

    if existing_user:
        # Check suspended tenant
        if existing_user.tenant and existing_user.tenant.status == "suspended" and not existing_user.is_platform_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your organization has been suspended. Please contact platform administrator.",
            )

        _enforce_oauth_sso_gate(
            db,
            existing_user.tenant_id,
            provider,
            user_role=existing_user.role,
            is_platform_admin=bool(existing_user.is_platform_admin),
        )

        # Update metadata if needed
        if not existing_user.avatar_url and avatar_url:
            existing_user.avatar_url = avatar_url
        if not existing_user.email:
            existing_user.email = email
        db.commit()
        db.refresh(existing_user)

        log_activity(
            tenant_id=existing_user.tenant_id or 1,
            user_id=existing_user.id,
            action="USER_LOGIN",
            category="AUTH",
            description=f"User '{existing_user.username}' signed in via {provider.capitalize()} OAuth"
        )

        return {
            "access_token": create_user_token(existing_user),
            "token_type": "bearer",
            "role": existing_user.role,
            "tenant_id": existing_user.tenant_id,
            "tenant_name": existing_user.tenant.name if existing_user.tenant else None,
            "is_platform_admin": bool(existing_user.is_platform_admin),
            "username": existing_user.username,
            "email": existing_user.email,
            "avatar_url": existing_user.avatar_url,
        }

    # 2. User does not exist: Provision new user with Corporate Domain Auto-Routing
    tenant = None
    assigned_role = "user"
    email_domain = email.split("@")[-1].lower().strip().rstrip(".")

    # 2a. Check both TenantSSOConfig.allowed_domains and Tenant.allowed_domains
    if email_domain and email_domain not in PUBLIC_EMAIL_DOMAINS:
        sso_match = find_tenant_sso_by_email(email, db)
        if sso_match:
            tenant, _ = sso_match
            assigned_role = "user"

    # 2b. Explicit company_name or join_code from request_body
    if not tenant:
        if request_body.company_name and request_body.company_name.strip():
            company_clean = request_body.company_name.strip()
            slug = slugify(company_clean)
            tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
            if tenant is None:
                auto_domain = (
                    email_domain
                    if email_domain not in PUBLIC_EMAIL_DOMAINS and not _is_domain_claimed(db, email_domain)
                    else None
                )
                tenant = Tenant(
                    name=company_clean,
                    slug=slug,
                    status="active",
                    join_code=generate_join_code(),
                    allowed_domains=auto_domain,
                    monthly_token_budget=500000,
                    current_month_tokens=0,
                    budget_reset_at=datetime.utcnow()
                )
                db.add(tenant)
                db.flush()
                assigned_role = "superadmin"
            else:
                if tenant.status == "suspended":
                    raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
                if not request_body.join_code or request_body.join_code.strip() != (tenant.join_code or "").strip():
                    raise HTTPException(status_code=403, detail="Invalid or missing join code for this organization")
                assigned_role = "user"
        elif request_body.join_code and request_body.join_code.strip():
            target_tenant = db.query(Tenant).filter(Tenant.join_code == request_body.join_code.strip()).first()
            if not target_tenant:
                raise HTTPException(status_code=400, detail="Invalid organization join code")
            if target_tenant.status == "suspended":
                raise HTTPException(status_code=403, detail="Cannot register into a suspended organization")
            tenant = target_tenant
            assigned_role = "user"
        else:
            # Fallback to Default Organization (Tenant #1)
            tenant = db.query(Tenant).filter(Tenant.id == 1).first() or db.query(Tenant).first()
            if tenant and tenant.status == "suspended":
                raise HTTPException(status_code=403, detail="Default organization is suspended. Please contact platform administrator.")
            assigned_role = "user"

    # Enforce SSO requirement before provisioning new social OAuth member
    if tenant and assigned_role != "superadmin":
        _enforce_oauth_sso_gate(db, tenant.id, provider, user_role=assigned_role, is_platform_admin=False)

    # Synchronize PostgreSQL auto-increment sequences before user insertion
    from src.database import engine
    from sqlalchemy import text
    if engine.dialect.name == "postgresql":
        try:
            db.execute(text("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE((SELECT MAX(id) FROM tenants), 1));"))
            db.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE((SELECT MAX(id) FROM users), 1));"))
        except Exception as seq_err:
            logger.warning(f"OAuth sequence sync notice: {seq_err}")

    # Generate unique username from name or email
    base_user = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(" ", "_")).strip()
    if not base_user or len(base_user) < 3:
        base_user = email.split("@")[0].lower()
    base_user = re.sub(r'[^a-zA-Z0-9_]', '', base_user)[:20]

    unique_username = base_user
    counter = 1
    while db.query(User).filter(User.username == unique_username).first():
        unique_username = f"{base_user}_{counter}"
        counter += 1

    new_user = User(
        username=unique_username,
        email=email,
        auth_provider=provider,
        oauth_id=oauth_id,
        avatar_url=avatar_url,
        hashed_password=None,
        role=assigned_role,
        tenant_id=tenant.id if tenant else None,
        is_platform_admin=False
    )
    try:
        db.add(new_user)
        db.flush()

        if tenant and assigned_role == "superadmin" and tenant.superadmin_user_id is None:
            tenant.superadmin_user_id = new_user.id

        db.commit()
        db.refresh(new_user)
    except IntegrityError as ie:
        db.rollback()
        logger.warning(f"OAuth provisioning conflict: {ie}")
        raise HTTPException(
            status_code=409,
            detail="Account or organization already exists. Please sign in or verify your organization join code."
        )

    if tenant:
        log_activity(
            tenant_id=tenant.id,
            user_id=new_user.id,
            action="USER_REGISTER",
            category="AUTH",
            description=f"User '{new_user.username}' registered via {provider.capitalize()} OAuth in '{tenant.name}'"
        )

    return {
        "access_token": create_user_token(new_user),
        "token_type": "bearer",
        "role": new_user.role,
        "tenant_id": new_user.tenant_id,
        "tenant_name": tenant.name if tenant else None,
        "is_platform_admin": bool(new_user.is_platform_admin),
        "username": new_user.username,
        "email": new_user.email,
        "avatar_url": new_user.avatar_url,
    }

@router.get("/tenant/domains")
def get_tenant_domains(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns the allowed corporate email domains for the user's organization."""
    if not current_user.tenant_id:
        return {"allowed_domains": None}
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {"allowed_domains": tenant.allowed_domains}

@router.patch("/tenant/domains")
@limiter.limit("10/minute", key_func=get_user_rate_limit_key)
def update_tenant_domains(request: Request, update: TenantDomainUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Allows SuperAdmins and Admins to configure allowed email domains for 1-click corporate onboarding."""
    if current_user.role not in ["superadmin", "admin"]:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    tenant = db.query(Tenant).filter(Tenant.id == current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    raw_domains = (update.allowed_domains or "").strip().lower()
    if not raw_domains:
        tenant.allowed_domains = None
        db.commit()
        log_activity(
            tenant_id=tenant.id,
            user_id=current_user.id,
            action="TENANT_DOMAINS_CLEARED",
            category="GOVERNANCE",
            description="Cleared corporate domain restrictions (registration reverts to join code only)"
        )
        return {"status": "success", "allowed_domains": None}

    from src.sso.validators import validate_and_check_corporate_domains
    cleaned_domains = validate_and_check_corporate_domains(
        raw_domains=raw_domains,
        tenant_id=tenant.id,
        db=db,
        public_domains=PUBLIC_EMAIL_DOMAINS,
    )

    tenant.allowed_domains = ", ".join(cleaned_domains)
    db.commit()
    
    log_activity(
        tenant_id=tenant.id,
        user_id=current_user.id,
        action="TENANT_DOMAINS_UPDATED",
        category="GOVERNANCE",
        description=f"Configured allowed corporate domains: '{tenant.allowed_domains}'"
    )
    return {"status": "success", "allowed_domains": tenant.allowed_domains}


@router.post("/logout")
def logout(request: Request, current_user: User = Depends(get_current_user)):
    """
    Revokes the current JWT session token by adding its jti claim to the Redis blacklist.
    """
    from src.sso.revocation import blacklist_token
    import jwt
    import time
    from src.auth import SECRET_KEY, ALGORITHM

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti:
                ttl = 86400
                if exp:
                    remaining = int(exp - time.time())
                    if remaining > 0:
                        ttl = remaining
                blacklist_token(jti, expires_in_seconds=ttl, ttl_seconds=ttl)
        except Exception as e:
            logger.warning(f"Error parsing token for logout blacklist: {e}")

    return {"message": "Successfully logged out"}


