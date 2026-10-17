from datetime import datetime, timedelta
from typing import Optional, Any
import bcrypt
# Passlib 1.7.4 compatibility fix for bcrypt >= 4.1.0
if not hasattr(bcrypt, "__about__"):
    class BcryptAbout:
        __version__ = getattr(bcrypt, "__version__", "4.0.1")
    bcrypt.__about__ = BcryptAbout()

from passlib.context import CryptContext
import jwt
import os

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict) -> str:
    """Encode JWT access token with expiration."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def create_user_token(user: Any) -> str:
    """Helper to encode all tenant & authorization claims for a User."""
    return create_access_token({
        "sub": user.username,
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "role": user.role,
        "is_platform_admin": getattr(user, "is_platform_admin", False),
    })
