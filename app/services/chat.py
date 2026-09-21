from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ParticipantResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    role: str
    is_admin: bool
    is_muted: bool
    last_read_at: Optional[datetime] = None


class ConversationCreate(BaseModel):
    type: str  # "direct" or "group"
    participant_ids: List[int]  # for DM: exactly 1 other user. For group: N users
    name: Optional[str] = None
    description: Optional[str] = None


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


class ChatMessageCreate(BaseModel):
    content: str
    message_type: str = "text"
    attachment_url: Optional[str] = None
    related_ticket_id: Optional[int] = None


class ChatMessageResponse(BaseModel):
    id: int
    conversation_id: int
    sender_id: Optional[int] = None
    sender_name: Optional[str] = None
    content: str
    message_type: str
    attachment_url: Optional[str] = None
    related_ticket_id: Optional[int] = None
    is_edited: bool
    is_deleted: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


ConversationResponse.model_rebuild()