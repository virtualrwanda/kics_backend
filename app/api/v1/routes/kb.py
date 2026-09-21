import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, desc
from typing import List, Optional

from ....core.database import get_db
from ....core.dependencies import get_current_user, require_admin
from ....models.user import User
from ....models.knowledge_base import KnowledgeArticle
from ....schemas.kb import (
    ArticleCreate, ArticleUpdate, ArticleResponse, ArticleFeedback,
)

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:250]


@router.get("/articles", response_model=List[ArticleResponse])
async def list_articles(
    search: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(KnowledgeArticle).where(KnowledgeArticle.is_published == True)
    if category:
        query = query.where(KnowledgeArticle.category == category)
    if search:
        query = query.where(
            or_(
                KnowledgeArticle.title.like(f"%{search}%"),
                KnowledgeArticle.summary.like(f"%{search}%"),
                KnowledgeArticle.content.like(f"%{search}%"),
            )
        )
    query = query.order_by(desc(KnowledgeArticle.views)).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/articles/{slug}", response_model=ArticleResponse)
async def get_article(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.slug == slug)
    )
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.views = (article.views or 0) + 1
    await db.commit()
    return article


@router.post("/articles", response_model=ArticleResponse, status_code=201)
async def create_article(
    payload: ArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    slug = _slugify(payload.title)
    existing = await db.execute(
        select(KnowledgeArticle).where(KnowledgeArticle.slug == slug)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Article with same title exists")

    article = KnowledgeArticle(
        title=payload.title,
        slug=slug,
        summary=payload.summary,
        content=payload.content,
        category=payload.category,
        tags=payload.tags,
        is_published=payload.is_published,
        author_id=current_user.id,
    )
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return article


@router.put("/articles/{article_id}", response_model=ArticleResponse)
async def update_article(
    article_id: int,
    payload: ArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(article, k, v)
    await db.commit()
    await db.refresh(article)
    return article


@router.delete("/articles/{article_id}")
async def delete_article(
    article_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    article.is_published = False
    await db.commit()
    return {"message": "Article unpublished"}


@router.post("/articles/{article_id}/feedback")
async def article_feedback(
    article_id: int,
    payload: ArticleFeedback,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    article = await db.get(KnowledgeArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if payload.helpful:
        article.helpful_count = (article.helpful_count or 0) + 1
    else:
        article.not_helpful_count = (article.not_helpful_count or 0) + 1    await db.commit()
    return {"message": "Thanks for your feedback!"}