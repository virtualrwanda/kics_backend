from pydantic import BaseModel
from datetime import datetime


class CommentBase(BaseModel):
    content: str
    is_internal: bool = False


class CommentCreate(CommentBase):
    pass


class CommentResponse(CommentBase):
    id: int
    ticket_id: int
    author_id: int
    created_at: datetime

    class Config:
        from_attributes = True
