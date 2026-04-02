from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
import jwt
from jwt.exceptions import PyJWTError as JWTError
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.vendor import Vendor

logger = logging.getLogger("bmm-auth")

_login_attempts = defaultdict(list)
_LOGIN_WINDOW = 300
_LOGIN_MAX = 10

router = APIRouter(prefix="/auth", tags=["auth"])

from app.config import settings as _cfg
SECRET_KEY = _cfg.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480
RESET_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

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

    assistant_name = getattr(user, 'assistant_name', None)

    token_data = {
        "sub": user.email,
        "role": user.role,
        "vendor_id": user.id,
        "name": user.name,
        "is_vendor": is_vendor,
        "booth_number": booth_number,
        "assistant_name": assistant_name,
    }
    access_token = create_access_token(data=token_data)

    redirect = None
    if user.role == "cashier" and is_vendor and booth_number:
        redirect = "choose"
    elif user.role == "admin":
        redirect = "/admin/index.html"

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
        "assistant_name": assistant_name,
    }

@router.get("/me")
async def get_me(
    current_user: Vendor = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.routers.settings import collect_role_permissions

    permissions = await collect_role_permissions(db, current_user)
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "booth_number": current_user.booth_number,
        "is_vendor": getattr(current_user, 'is_vendor', False),
        "assistant_name": getattr(current_user, 'assistant_name', None),
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "sale_notify_preference": current_user.sale_notify_preference,
        "permissions": permissions,
    }


class DisplayPreferencesUpdate(BaseModel):
    theme_preference: Optional[str] = None
    font_size_preference: Optional[str] = None
    sale_notify_preference: Optional[str] = None


@router.put("/me/preferences")
async def update_preferences(
    prefs: DisplayPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(get_current_user),
):
    """Update the current user's display preferences."""
    valid_themes = {"dark", "light"}
    valid_font_sizes = {"small", "medium", "large"}

    if prefs.theme_preference is not None:
        if prefs.theme_preference not in valid_themes:
            raise HTTPException(status_code=400, detail=f"Invalid theme. Must be one of: {valid_themes}")
        current_user.theme_preference = prefs.theme_preference

    if prefs.font_size_preference is not None:
        if prefs.font_size_preference not in valid_font_sizes:
            raise HTTPException(status_code=400, detail=f"Invalid font size. Must be one of: {valid_font_sizes}")
        current_user.font_size_preference = prefs.font_size_preference

    valid_notify_prefs = {"instant", "daily", "weekly", "monthly"}
    if prefs.sale_notify_preference is not None:
        if prefs.sale_notify_preference not in valid_notify_prefs:
            raise HTTPException(status_code=400, detail=f"Invalid notification preference. Must be one of: {valid_notify_prefs}")
        current_user.sale_notify_preference = prefs.sale_notify_preference

    await db.commit()

    return {
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "sale_notify_preference": current_user.sale_notify_preference,
        "detail": "Preferences updated.",
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
            "assistant_name": getattr(current_user, 'assistant_name', None),
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

def _create_reset_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": email, "purpose": "password_reset", "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

def _verify_reset_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("purpose") != "password_reset":
            return None
        return payload.get("sub")
    except JWTError:
        return None

@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Vendor).where(func.lower(Vendor.email) == body.email.strip().lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        return {"detail": "If that email exists in our system, a reset link has been sent."}

    token = _create_reset_token(user.email)

    import os
    base_url = os.environ.get("BASE_URL", "")
    if not base_url:
        dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
        if dev_domain:
            base_url = f"https://{dev_domain}"
        else:
            base_url = "https://bowenstreetmarket.com"

    reset_url = f"{base_url}/vendor/reset-password.html?token={token}"

    html_body = f"""
    <div style="font-family: Georgia, serif; max-width: 520px; margin: 0 auto; color: #2A2825;">
        <div style="text-align: center; padding: 24px 0; border-bottom: 2px solid #C9A84C;">
            <h1 style="font-size: 1.6rem; margin: 0; color: #2A2825; font-style: italic;">Bowenstreet Market</h1>
            <p style="font-size: 0.85rem; color: #5a554d; margin: 4px 0 0;">Handcrafted &middot; Vintage &middot; Antique</p>
        </div>
        <div style="padding: 32px 16px;">
            <p>Hi {user.name},</p>
            <p>We received a request to reset your password for your Bowenstreet Market account.</p>
            <p style="text-align: center; margin: 28px 0;">
                <a href="{reset_url}" style="display: inline-block; background: #C9A84C; color: #2A2825; padding: 12px 32px; text-decoration: none; font-weight: 600; font-size: 1rem;">
                    Reset My Password
                </a>
            </p>
            <p style="font-size: 0.85rem; color: #5a554d;">This link will expire in 60 minutes. If you didn't request a password reset, you can safely ignore this email.</p>
            <p style="font-size: 0.85rem; color: #5a554d;">If the button doesn't work, copy and paste this link into your browser:</p>
            <p style="font-size: 0.75rem; color: #888; word-break: break-all;">{reset_url}</p>
        </div>
        <div style="text-align: center; padding: 16px; border-top: 1px solid #eee; font-size: 0.75rem; color: #999;">
            Bowenstreet Market &middot; 2837 Bowen St, Oshkosh WI 54901
        </div>
    </div>
    """

    plain_body = f"Hi {user.name},\n\nReset your Bowenstreet Market password here:\n{reset_url}\n\nThis link expires in 60 minutes.\n\nBowenstreet Market\n2837 Bowen St, Oshkosh WI 54901"

    from app.services.email import send_email_safe
    email_result = await send_email_safe(
        to_email=user.email,
        subject="Reset Your Bowenstreet Market Password",
        html_body=html_body,
        plain_body=plain_body,
    )

    if not email_result.get("success"):
        logger.error(f"Failed to send reset email to {user.email}: {email_result.get('error')}")

    return {"detail": "If that email exists in our system, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password_with_token(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    email = _verify_reset_token(body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link. Please request a new one.")

    result = await db.execute(
        select(Vendor).where(func.lower(Vendor.email) == email.lower())
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Account not found")

    user.password_hash = get_password_hash(body.new_password)
    user.password_changed = True
    await db.commit()

    logger.info(f"Password reset completed for {user.email}")
    return {"detail": "Password has been reset successfully. You can now sign in with your new password."}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Vendor = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = get_password_hash(body.new_password)
    current_user.password_changed = True
    await db.commit()

    return {"detail": "Password changed successfully"}
