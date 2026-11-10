from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import jwt
from jwt.exceptions import InvalidTokenError

from src.database import SessionLocal
from src.models import User
from src.auth import SECRET_KEY, ALGORITHM

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception

    # Cross-check: If JWT includes tenant_id, verify it matches DB
    token_tenant_id = payload.get("tenant_id")
    if token_tenant_id is not None and user.tenant_id != token_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session tenant context mismatch. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Cross-check: If tenant is suspended, deny access (unless platform superadmin)
    if user.tenant and user.tenant.status == "suspended" and not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization has been suspended. Please contact platform administrator.",
        )

    # Check session revocation / blacklist (Phase 12 Enterprise SSO)
    from src.sso.revocation import is_session_revoked, is_token_blacklisted
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_iat = payload.get("iat")
    # For platform admins, do not check tenant session revocation to avoid lockout by tenant actions
    check_tenant_id = None if user.is_platform_admin else user.tenant_id
    if is_session_revoked(user_id=user.id, tenant_id=check_tenant_id, token_iat=token_iat):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been revoked by organization administrator.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user

def get_current_editor_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ["editor", "admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Editor privileges or higher required")
    return current_user

def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ["admin", "superadmin"]:
        raise HTTPException(status_code=403, detail="Tenant Admin privileges or higher required")
    return current_user

def get_current_superadmin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Tenant SuperAdmin privileges required")
    return current_user

def get_current_platform_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform SuperAdmin privileges required")
    return current_user
