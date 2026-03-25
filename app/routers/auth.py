from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

import os
from app.database import get_db
from app.models.vendor import Vendor

logger = logging.getLogger("bmm-auth")

_login_attempts = defaultdict(list)
_LOGIN_WINDOW = 300
_LOGIN_MAX = 10

router = APIRouter(prefix="/auth", tags=["auth"])

SECRET_KEY = os.environ.get("SECRET_KEY", "bmm-pos-dev-fallback-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def verify_password(plain_password, hashed_password):
    try:
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def get_password_hash(password):
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(Vendor).where(Vendor.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user

def require_role(*roles):
    async def role_checker(current_user: Vendor = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker

require_admin = require_role("admin")
require_cashier_or_admin = require_role("admin", "cashier")

@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    _login_attempts[client_ip] = [t for t in _login_attempts[client_ip] if now - t < _LOGIN_WINDOW]
    if len(_login_attempts[client_ip]) >= _LOGIN_MAX:
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a few minutes.")

    result = await db.execute(select(Vendor).where(func.lower(Vendor.email) == form_data.username.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        _login_attempts[client_ip].append(now)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")

    is_vendor = getattr(user, 'is_vendor', False) or False
    booth_number = getattr(user, 'booth_number', None)

    token_data = {
        "sub": user.email,
        "role": user.role,
        "vendor_id": user.id,
        "name": user.name,
        "is_vendor": is_vendor,
        "booth_number": booth_number,
    }
    access_token = create_access_token(data=token_data)

    redirect = None
    if user.role in ("admin", "cashier") and is_vendor and booth_number:
        redirect = "choose"

    first_login = not getattr(user, 'password_changed', True)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "vendor_id": user.id,
        "name": user.name,
        "is_vendor": is_vendor,
        "booth_number": booth_number,
        "redirect": redirect,
        "first_login": first_login,
    }

@router.get("/me")
async def get_me(current_user: Vendor = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "booth_number": current_user.booth_number,
        "is_vendor": getattr(current_user, 'is_vendor', False),
    }

@router.post("/refresh")
async def refresh_token(current_user: Vendor = Depends(get_current_user)):
    access_token = create_access_token(
        data={
            "sub": current_user.email,
            "role": current_user.role,
            "vendor_id": current_user.id,
            "name": current_user.name,
            "is_vendor": getattr(current_user, 'is_vendor', False) or False,
            "booth_number": getattr(current_user, 'booth_number', None),
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}
