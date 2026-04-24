from datetime import datetime, timedelta, timezone
from typing import Optional
from collections import defaultdict
import logging
import secrets
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
from app.services.rate_limit import check_rate_limit

logger = logging.getLogger("bmm-auth")

router = APIRouter(prefix="/auth", tags=["auth"])

from app.config import settings as _cfg
SECRET_KEY = _cfg.secret_key
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = _cfg.access_token_expire_hours * 60
RESET_TOKEN_EXPIRE_MINUTES = 60
MIN_PASSWORD_LENGTH = 10

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def verify_password(plain_password, hashed_password):
    try:
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = hashed_password.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False

def _validate_password_strength(password: str) -> str:
    """Return error message if password is too weak, otherwise empty string."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    if not any(c.isupper() for c in password):
        return "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit"
    if not any(c in "!@#$%^&*()-_=+[]{}|;:'\",.<>?/~`" for c in password):
        return "Password must contain at least one special character"
    return ""


def get_password_hash(password):
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password_bytes, salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def _build_credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _resolve_user_from_token(token: str, db: AsyncSession) -> Vendor:
    credentials_exception = _build_credentials_exception()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(Vendor).where(Vendor.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception

    token_auth_version = int(payload.get("av", 0) or 0)
    current_auth_version = int(getattr(user, "auth_version", 0) or 0)
    if token_auth_version != current_auth_version:
        raise credentials_exception

    return user


async def get_user_from_authorization_header(authorization: str, db: AsyncSession) -> Vendor:
    token = authorization.replace("Bearer ", "", 1).strip() if authorization.lower().startswith("bearer ") else authorization.strip()
    if not token:
        raise _build_credentials_exception()
    return await _resolve_user_from_token(token, db)


async def get_user_from_token(token: str, db: AsyncSession) -> Vendor:
    return await _resolve_user_from_token(token, db)


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    return await _resolve_user_from_token(token, db)


def bump_auth_version(user: Vendor) -> None:
    user.auth_version = int(getattr(user, "auth_version", 0) or 0) + 1

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
    check_rate_limit(
        request,
        window_name="login",
        max_requests=10,
        window_seconds=300,
        error_message="Too many login attempts. Please wait a few minutes.",
    )

    result = await db.execute(select(Vendor).where(func.lower(Vendor.email) == form_data.username.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")

    is_vendor = getattr(user, 'is_vendor', False) or False
    booth_number = getattr(user, 'booth_number', None)

    assistant_name = getattr(user, 'assistant_name', None)
    assistant_enabled = getattr(user, 'assistant_enabled', True)
    auto_payout_enabled = getattr(user, 'auto_payout_enabled', True)

    token_data = {
        "sub": user.email,
        "role": user.role,
        "vendor_id": user.id,
        "name": user.name,
        "av": int(getattr(user, "auth_version", 0) or 0),
        "is_vendor": is_vendor,
        "booth_number": booth_number,
        "assistant_name": assistant_name,
        "assistant_enabled": assistant_enabled,
        "auto_payout_enabled": auto_payout_enabled,
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
        "assistant_enabled": assistant_enabled,
        "auto_payout_enabled": auto_payout_enabled,
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
        "assistant_enabled": getattr(current_user, 'assistant_enabled', True),
        "auto_payout_enabled": getattr(current_user, 'auto_payout_enabled', True),
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "sale_notify_preference": current_user.sale_notify_preference,
        "permissions": permissions,
    }


class DisplayPreferencesUpdate(BaseModel):
    theme_preference: Optional[str] = None
    font_size_preference: Optional[str] = None
    sale_notify_preference: Optional[str] = None
    auto_payout_enabled: Optional[bool] = None


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

    if prefs.auto_payout_enabled is not None:
        current_user.auto_payout_enabled = bool(prefs.auto_payout_enabled)

    await db.commit()

    return {
        "theme_preference": current_user.theme_preference,
        "font_size_preference": current_user.font_size_preference,
        "sale_notify_preference": current_user.sale_notify_preference,
        "auto_payout_enabled": getattr(current_user, 'auto_payout_enabled', True),
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
            "av": int(getattr(current_user, "auth_version", 0) or 0),
            "is_vendor": getattr(current_user, 'is_vendor', False) or False,
            "booth_number": getattr(current_user, 'booth_number', None),
            "assistant_name": getattr(current_user, 'assistant_name', None),
            "assistant_enabled": getattr(current_user, 'assistant_enabled', True),
            "auto_payout_enabled": getattr(current_user, 'auto_payout_enabled', True),
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    token: str
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

import random
import string

from app.models.password_reset_code import PasswordResetCode


def _generate_reset_code() -> str:
    """Generate a random 6-digit reset code."""
    return ''.join(random.choices(string.digits, k=6))


@router.post("/forgot-password")
async def forgot_password(request: Request, body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    check_rate_limit(
        request,
        window_name="forgot_password",
        max_requests=5,
        window_seconds=3600,
        error_message="Too many password reset requests. Please wait an hour.",
    )

    result = await db.execute(
        select(Vendor).where(func.lower(Vendor.email) == body.email.strip().lower())
    )
    user = result.scalar_one_or_none()

    if not user:
        return {"detail": "If that email exists in our system, a reset code has been sent."}

    # Invalidate any existing unused codes for this email
    await db.execute(
        select(PasswordResetCode)
        .where(PasswordResetCode.email == user.email.lower(), PasswordResetCode.used == False)
    )
    # Mark existing codes as used
    from sqlalchemy import update
    await db.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.email == user.email.lower(), PasswordResetCode.used == False)
        .values(used=True)
    )

    code = _generate_reset_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

    reset_entry = PasswordResetCode(
        email=user.email.lower(),
        code=code,
        expires_at=expires_at,
        used=False,
    )
    db.add(reset_entry)
    await db.commit()

    # Build reset URL with email and code pre-filled
    scheme = request.headers.get("x-forwarded-proto") or "https"
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    base_url = f"{scheme}://{host}".rstrip("/")
    reset_url = f"{base_url}/vendor/reset-password.html?email={user.email.lower()}&code={code}"

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
                <a href="{reset_url}" style="display: inline-block; background: #C9A84C; color: #2A2825; padding: 14px 28px; text-decoration: none; font-weight: 600; font-size: 1rem; border-radius: 4px;">Reset Your Password</a>
            </p>
            <p style="font-size: 0.85rem; color: #5a554d; text-align: center;">Click the button above or use this code on the <a href="{reset_url}">password reset page</a>:</p>
            <p style="text-align: center; margin: 16px 0; font-size: 1.4rem; font-weight: 600; letter-spacing: 0.2em; background: #f5f5f0; padding: 16px; border: 2px solid #C9A84C; color: #2A2825;">
                {code}
            </p>
            <p style="font-size: 0.85rem; color: #5a554d; text-align: center;">This code is NOT your new password. It is only used to verify your identity.</p>
            <p style="font-size: 0.85rem; color: #5a554d;">This code will expire in 60 minutes. If you didn't request a password reset, you can safely ignore this email.</p>
        </div>
        <div style="text-align: center; padding: 16px; border-top: 1px solid #eee; font-size: 0.75rem; color: #999;">
            Bowenstreet Market &middot; 2837 Bowen St, Oshkosh WI 54901
        </div>
    </div>
    """

    plain_body = f"""Hi {user.name},

We received a request to reset your password for your Bowenstreet Market account.

Reset your password here:
{reset_url}

Or use this code on the password reset page: {code}

This code is NOT your new password. It is only used to verify your identity.
This code expires in 60 minutes.

Bowenstreet Market
2837 Bowen St, Oshkosh WI 54901"""

    from app.services.email import send_email_safe
    email_result = await send_email_safe(
        to_email=user.email,
        subject="Your Bowenstreet Market Password Reset Code",
        html_body=html_body,
        plain_body=plain_body,
    )

    if not email_result.get("success"):
        logger.error(f"Failed to send reset email to {user.email}: {email_result.get('error')}")

    return {"detail": "If that email exists in our system, a reset code has been sent."}


@router.post("/reset-password")
async def reset_password_with_token(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    pw_err = _validate_password_strength(body.new_password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)

    # Verify the reset code (case-insensitive email match)
    result = await db.execute(
        select(PasswordResetCode)
        .where(
            func.lower(PasswordResetCode.email) == body.email.strip().lower(),
            PasswordResetCode.code == body.token,
            PasswordResetCode.used == False,
            PasswordResetCode.expires_at > datetime.now(timezone.utc),
        )
    )
    reset_code = result.scalar_one_or_none()

    if not reset_code:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code. Please request a new one.")

    result = await db.execute(
        select(Vendor).where(func.lower(Vendor.email) == body.email.strip().lower())
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Account not found")

    user.password_hash = get_password_hash(body.new_password)
    user.password_changed = True
    bump_auth_version(user)

    # Mark code as used
    reset_code.used = True
    await db.commit()

    logger.info(f"Password reset completed for {user.email}")
    return {"detail": "Password has been reset successfully. You can now sign in with your new password."}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Vendor = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pw_err = _validate_password_strength(body.new_password)
    if pw_err:
        raise HTTPException(status_code=400, detail=pw_err)

    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = get_password_hash(body.new_password)
    current_user.password_changed = True
    bump_auth_version(current_user)
    await db.commit()

    return {"detail": "Password changed successfully"}
