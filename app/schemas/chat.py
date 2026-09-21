from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ============================================================
# PARTICIPANTS
# ============================================================
class ParticipantResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    role: str
    avatar_url: Optional[str] = None
    is_admin: bool = False
    is_muted: bool = False
    last_read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# CONVERSATIONS
# ============================================================
class ConversationCreate(BaseModel):
    """Create a DM (1 other user) or a group conversation."""
    type: str  # "direct" or "group"
    participant_ids: List[int]
    name: Optional[str] = None          # required for groups
    description: Optional[str] = None   # optional for groups


class ConversationResponse(BaseModel):
    id: int
    type: str
    name: Optional[str] = None
    description: Optional[str] = None
    participants: List[ParticipantResponse] = []
    last_message: Optional["ChatMessageResponse"] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# MESSAGES
# ============================================================
class ChatMessageCreate(BaseModel):
    """Send a text message (use /upload for files)."""
    content: str
    message_type: str = "text"      # "text" | "image" | "file" | "system"
    attachment_url: Optional[str] = None
    related_ticket_id: Optional[int] = None


class ChatMessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: Optional[int] = None
    sender_name: Optional[str] = None
    sender_avatar_url: Optional[str] = None    # for message bubbles
    content: str
    message_type: str = "text"
    attachment_url: Optional[str] = None
    related_ticket_id: Optional[int] = None
    is_edited: bool = False
    is_deleted: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================
# UPLOAD
# ============================================================
class AttachmentUploadResponse(BaseModel):
    """Returned after POST /chat/conversations/{id}/upload."""
    message: ChatMessageResponse
    upload: "UploadInfo"


class UploadInfo(BaseModel):
    url: str
    filename: str
    stored_name: Optional[str] = None
    size_bytes: int
    content_type: Optional[str] = None
    is_image: bool = False


# ============================================================
# READ RECEIPTS
# ============================================================
class MarkReadResponse(BaseModel):
    message: str = "Marked as read"


# ============================================================
# FORWARD REFERENCES
# ============================================================
ConversationResponse.model_rebuild()
AttachmentUploadResponse.model_rebuild()