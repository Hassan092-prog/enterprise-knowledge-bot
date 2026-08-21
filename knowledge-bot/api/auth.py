from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from src.models import User, AccessRequest
from api.dependencies import get_db, get_current_user
from src.auth import verify_password, get_password_hash, create_access_token

router = APIRouter()

class UserCreate(BaseModel):
    username: str
    password: str

class RoleRequest(BaseModel):
    role: str

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/register", response_model=Token)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user_data.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = get_password_hash(user_data.password)
    db_user = User(username=user_data.username, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    access_token = create_access_token(data={"sub": db_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
def login(user_data: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == user_data.username).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role
    }

@router.post("/request_role")
def request_role(role_req: RoleRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if role_req.role not in ["editor", "admin"]:
        raise HTTPException(status_code=400, detail="Invalid role requested")
    
    # Check if already requested
    existing = db.query(AccessRequest).filter(AccessRequest.user_id == current_user.id, AccessRequest.status == "pending").first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending request")
        
    req = AccessRequest(user_id=current_user.id, requested_role=role_req.role)
    db.add(req)
    db.commit()
    return {"status": "success"}

@router.get("/my_request")
def my_request(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    req = db.query(AccessRequest).filter(AccessRequest.user_id == current_user.id).order_by(AccessRequest.created_at.desc()).first()
    if req:
        return {"requested_role": req.requested_role, "status": req.status}
    return None
