"""Secure file upload helpers — path traversal prevention, filename sanitization, MIME validation."""
import os
import uuid
from pathlib import Path

from fastapi import UploadFile, HTTPException


# Whitelist of allowed image MIME types and their magic signatures
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}

_MAX_FILENAME_LENGTH = 200


def _sanitize_filename(raw_name: str) -> str:
    """
    Strip path traversal, control characters, and unsafe chars from a filename.
    Returns a safe basename or raises HTTPException.
    """
    if not raw_name:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Normalize to basename only — prevent path traversal
    basename = os.path.basename(raw_name)

    # Strip null bytes and control chars
    basename = basename.replace("\x00", "").replace("\n", "").replace("\r", "")

    # Remove leading dots (hidden files) and slashes
    basename = basename.lstrip(".").lstrip("/")

    if not basename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    if len(basename) > _MAX_FILENAME_LENGTH:
        basename = basename[:_MAX_FILENAME_LENGTH]

    # Keep only safe characters
    safe = []
    for ch in basename:
        if ch.isalnum() or ch in "._-":
            safe.append(ch)
        else:
            safe.append("_")

    result = "".join(safe)
    if not result or result.startswith("."):
        result = f"upload_{result}"

    return result


def _secure_save_path(upload_dir: str, filename: str) -> str:
    """
    Return an absolute, safe path inside upload_dir.
    Raises if the resolved path escapes upload_dir.
    """
    base = Path(upload_dir).resolve()
    target = (base / filename).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid upload path")
    return str(target)


def _validate_image_content(contents: bytes, declared_content_type: str) -> None:
    """Verify file magic bytes match declared MIME type."""
    expected = _ALLOWED_IMAGE_TYPES.get(declared_content_type.lower())
    if not expected:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {declared_content_type}")
    if not any(contents.startswith(sig) for sig in expected):
        raise HTTPException(status_code=400, detail="File content does not match declared image type")


def secure_image_filename(original_name: str, preferred_ext: str = ".jpg") -> str:
    """Generate a safe, unique filename for an image upload."""
    sanitized = _sanitize_filename(original_name)
    stem = Path(sanitized).stem
    unique = uuid.uuid4().hex[:10]
    return f"{stem}_{unique}{preferred_ext}"


def save_upload(upload_dir: str, filename: str, data: bytes) -> str:
    """Safely write upload data to disk. Returns the resolved path."""
    filepath = _secure_save_path(upload_dir, filename)
    os.makedirs(os.path.dirname(filepath) or upload_dir, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(data)
    return filepath
