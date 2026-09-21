"""
File storage service for chat attachments and user avatars.
Stores files on disk under ./uploads/.
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Tuple

from fastapi import UploadFile, HTTPException

logger = logging.getLogger(__name__)

# Base directory for all uploads
UPLOAD_ROOT = Path("uploads")
CHAT_DIR = UPLOAD_ROOT / "chat"
AVATAR_DIR = UPLOAD_ROOT / "avatars"

# Ensure directories exist
for d in (UPLOAD_ROOT, CHAT_DIR, AVATAR_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# CONFIG
# ============================================================
MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
ALLOWED_DOC_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".zip", ".rar",
}
ALLOWED_ALL_EXT = ALLOWED_IMAGE_EXT | ALLOWED_DOC_EXT


# ============================================================
# VALIDATION
# ============================================================
def _validate_file(file: UploadFile, allowed_ext: set, max_size: int = MAX_FILE_SIZE_BYTES):
    """Raise HTTPException if file is invalid."""
    # Check filename
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {sorted(allowed_ext)}",
        )

    # Check Content-Type header
    if file.content_type and not file.content_type.startswith(("image/", "application/", "text/")):
        raise HTTPException(status_code=400, detail="Invalid content type")

    return ext


async def _save_to_disk(file: UploadFile, folder: Path, prefix: str) -> Tuple[str, int]:
    """Save uploaded file to disk. Returns (filename, size_bytes)."""
    ext = Path(file.filename).suffix.lower()
    unique_name = f"{prefix}_{uuid.uuid4().hex}{ext}"
    dest = folder / unique_name

    # Stream write with size check
    size = 0
    try:
        with dest.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 256)  # 256 KB chunks
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_SIZE_BYTES:
                    f.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit",
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        logger.error(f"File save failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")

    return unique_name, size


# ============================================================
# PUBLIC API
# ============================================================
async def save_chat_attachment(file: UploadFile) -> dict:
    """
    Save a chat attachment (image or document).
    Returns dict with url, filename, size, content_type, is_image.
    """
    ext = _validate_file(file, ALLOWED_ALL_EXT)
    unique_name, size = await _save_to_disk(file, CHAT_DIR, "chat")

    is_image = ext in ALLOWED_IMAGE_EXT
    return {
        "url": f"/uploads/chat/{unique_name}",
        "filename": file.filename,
        "stored_name": unique_name,
        "size_bytes": size,
        "content_type": file.content_type,
        "is_image": is_image,
    }


async def save_avatar(file: UploadFile) -> dict:
    """
    Save a user profile picture.
    Only images allowed.
    """
    ext = _validate_file(file, ALLOWED_IMAGE_EXT, max_size=5 * 1024 * 1024)  # 5 MB max for avatars
    unique_name, size = await _save_to_disk(file, AVATAR_DIR, "avatar")
    return {
        "url": f"/uploads/avatars/{unique_name}",
        "filename": file.filename,
        "stored_name": unique_name,
        "size_bytes": size,
        "content_type": file.content_type,
    }


def delete_file(url_path: str) -> bool:
    """Delete a file given its URL path (e.g., '/uploads/chat/xyz.jpg')."""
    if not url_path or not url_path.startswith("/uploads/"):
        return False
    rel = url_path[len("/uploads/"):]
    target = UPLOAD_ROOT / rel
    try:
        if target.exists() and target.is_file():
            target.unlink()
            return True
    except Exception as e:
        logger.warning(f"Failed to delete {target}: {e}")
    return False