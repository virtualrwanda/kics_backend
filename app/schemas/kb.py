from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ArticleBase(BaseModel):
    title: str
    summary: Optional[str] = None
    content: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None


class ArticleCreate(ArticleBase):
    is_published: bool = True


class ArticleUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    is_published: Optional[bool] = None


class ArticleResponse(ArticleBase):
    id: int
    slug: Optional[str] = None
    is_published: bool
    views: int
    helpful_count: int
    not_helpful_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArticleFeedback(BaseModel):
    helpful: bool