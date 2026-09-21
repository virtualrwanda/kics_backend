from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    File,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, desc
from typing import List, Optional
from datetime import datetime

from ....core.database import get_db
from ....core.dependencies import get_current_user
from ....models.user import User, UserRole
from ....models.chat import (
    Conversation,
    ConversationType,
    ConversationParticipant,
    ChatMessage,
    MessageRead,
)
from ....schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ParticipantResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    AttachmentUploadResponse,
    UploadInfo,
    MarkReadResponse,
)
from ....services.ws_manager import manager

# File service is imported lazily to avoid crashing the app
try:
    from ....services import file_service
    FILE_SERVICE_AVAILABLE = True
except Exception as e:
    print(f"⚠️  file_service unavailable — uploads will fail: {e}")
    FILE_SERVICE_AVAILABLE = False
    file_service = None  # type: ignore


router = APIRouter(prefix="/chat", tags=["Chat"])


# ============================================================
# HELPERS
# ============================================================
async def _assert_participant(
    db: AsyncSession, conversation_id: int, user_id: int
) -> ConversationParticipant:
    result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    )
    participant = result.scalar_one_or_none()
    if not participant:
        raise HTTPException(status_code=403, detail="Not a participant")
    return participant


async def _participant_ids(db: AsyncSession, conversation_id: int) -> List[int]:
    result = await db.execute(
        select(ConversationParticipant.user_id).where(
            ConversationParticipant.conversation_id == conversation_id
        )
    )
    return [row[0] for row in result.all()]


async def _build_message_response(
    db: AsyncSession, msg: ChatMessage
) -> ChatMessageResponse:
    sender_name = None
    sender_avatar = None
    if msg.sender_id:
        sender = await db.get(User, msg.sender_id)
        if sender:
            sender_name = sender.full_name
            sender_avatar = sender.avatar_url

    return ChatMessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_name=sender_name,
        sender_avatar_url=sender_avatar,
        content=msg.content,
        message_type=msg.message_type,
        attachment_url=msg.attachment_url,
        related_ticket_id=msg.related_ticket_id,
        is_edited=msg.is_edited,
        is_deleted=msg.is_deleted,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
    )


async def _build_conversation_response(
    db: AsyncSession, conv: Conversation, current_user_id: int
) -> ConversationResponse:
    parts_result = await db.execute(
        select(ConversationParticipant, User)
        .join(User, User.id == ConversationParticipant.user_id)
        .where(ConversationParticipant.conversation_id == conv.id)
    )
    participants = []
    for cp, u in parts_result.all():
        participants.append(
            ParticipantResponse(
                user_id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role.value if hasattr(u.role, "value") else str(u.role),
                avatar_url=u.avatar_url,
                is_admin=cp.is_admin,
                is_muted=cp.is_muted,
                last_read_at=cp.last_read_at,
            )
        )

    last_msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conv.id)
        .order_by(desc(ChatMessage.created_at))
        .limit(1)
    )
    last_msg = last_msg_result.scalar_one_or_none()
    last_message = await _build_message_response(db, last_msg) if last_msg else None

    my_part_result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conv.id,
                ConversationParticipant.user_id == current_user_id,
            )
        )
    )
    my_part = my_part_result.scalar_one_or_none()
    unread_count = 0
    if my_part:
        cutoff = my_part.last_read_at or datetime(1970, 1, 1)
        unread_result = await db.execute(
            select(func.count()).select_from(ChatMessage).where(
                and_(
                    ChatMessage.conversation_id == conv.id,
                    ChatMessage.created_at > cutoff,
                    ChatMessage.sender_id != current_user_id,
                )
            )
        )
        unread_count = unread_result.scalar() or 0

    return ConversationResponse(
        id=conv.id,
        type=conv.type.value if hasattr(conv.type, "value") else str(conv.type),
        name=conv.name,
        description=conv.description,
        participants=participants,
        last_message=last_message,
        unread_count=unread_count,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


async def _create_system_message(
    db: AsyncSession, conversation_id: int, text: str
) -> ChatMessage:
    msg = ChatMessage(
        conversation_id=conversation_id,
        sender_id=None,
        content=text,
        message_type="system",
    )
    db.add(msg)
    await db.flush()
    return msg


# ============================================================
# CREATE CONVERSATION (DM or GROUP)
# ============================================================
@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.type not in ("direct", "group"):
        raise HTTPException(status_code=400, detail="type must be 'direct' or 'group'")

    # ----- DIRECT -----
    if payload.type == "direct":
        if len(payload.participant_ids) != 1:
            raise HTTPException(
                status_code=400, detail="DM requires exactly 1 other participant"
            )
        other_id = payload.participant_ids[0]
        if other_id == current_user.id:
            raise HTTPException(status_code=400, detail="Cannot DM yourself")

        other_user = await db.get(User, other_id)
        if not other_user or not other_user.is_active:
            raise HTTPException(status_code=404, detail="User not found")

        existing_convs = await db.execute(
            select(Conversation)
            .join(
                ConversationParticipant,
                ConversationParticipant.conversation_id == Conversation.id,
            )
            .where(Conversation.type == ConversationType.DIRECT)
            .group_by(Conversation.id)
            .having(func.count(ConversationParticipant.user_id) == 2)
        )
        for conv in existing_convs.scalars().all():
            ids_result = await db.execute(
                select(ConversationParticipant.user_id).where(
                    ConversationParticipant.conversation_id == conv.id
                )
            )
            ids = {row[0] for row in ids_result.all()}
            if ids == {current_user.id, other_id}:
                return await _build_conversation_response(db, conv, current_user.id)

        conv = Conversation(type=ConversationType.DIRECT, created_by=current_user.id)
        db.add(conv)
        await db.flush()
        participant_ids = [current_user.id, other_id]

    # ----- GROUP -----
    else:
        if not payload.name or not payload.name.strip():
            raise HTTPException(status_code=400, detail="Group requires a name")

        participant_ids = list({current_user.id, *payload.participant_ids})
        existing_users_result = await db.execute(
            select(User.id).where(
                User.id.in_(participant_ids), User.is_active == True
            )
        )
        existing_ids = {row[0] for row in existing_users_result.all()}
        missing = set(participant_ids) - existing_ids
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Users not found or inactive: {sorted(missing)}",
            )

        conv = Conversation(
            type=ConversationType.GROUP,
            name=payload.name.strip(),
            description=(payload.description or "").strip() or None,
            created_by=current_user.id,
        )
        db.add(conv)
        await db.flush()

    # Add participants
    for uid in participant_ids:
        db.add(
            ConversationParticipant(
                conversation_id=conv.id,
                user_id=uid,
                is_admin=(uid == current_user.id and payload.type == "group"),
            )
        )

    if payload.type == "group":
        await _create_system_message(
            db, conv.id, f"{current_user.full_name} created this group"
        )

    await db.commit()
    await db.refresh(conv)

    # Broadcast
    try:
        await manager.broadcast(
            participant_ids,
            {
                "event": "conversation_created",
                "conversation_id": conv.id,
                "type": conv.type.value if hasattr(conv.type, "value") else str(conv.type),
                "name": conv.name,
                "created_by": current_user.id,
            },
        )
    except Exception as e:
        print(f"⚠️  WS broadcast failed (non-fatal): {e}")

    return await _build_conversation_response(db, conv, current_user.id)


# ============================================================
# LIST MY CONVERSATIONS
# ============================================================
@router.get("/conversations", response_model=List[ConversationResponse])
async def list_my_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Conversation)
        .join(
            ConversationParticipant,
            ConversationParticipant.conversation_id == Conversation.id,
        )
        .where(ConversationParticipant.user_id == current_user.id)
        .where(Conversation.is_active == True)
        .order_by(desc(Conversation.updated_at), desc(Conversation.created_at))
    )
    convs = result.scalars().all()
    return [await _build_conversation_response(db, c, current_user.id) for c in convs]


# ============================================================
# GET ONE CONVERSATION
# ============================================================
@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_participant(db, conversation_id, current_user.id)
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await _build_conversation_response(db, conv, current_user.id)


# ============================================================
# GET MESSAGES
# ============================================================
@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=List[ChatMessageResponse],
)
async def get_messages(
    conversation_id: int,
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_participant(db, conversation_id, current_user.id)

    query = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before_id:
        query = query.where(ChatMessage.id < before_id)
    query = query.order_by(desc(ChatMessage.created_at)).limit(limit)

    result = await db.execute(query)
    messages = list(reversed(result.scalars().all()))
    return [await _build_message_response(db, m) for m in messages]


# ============================================================
# SEND MESSAGE
# ============================================================
@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    conversation_id: int,
    payload: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_participant(db, conversation_id, current_user.id)

    msg = ChatMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=payload.content,
        message_type=payload.message_type or "text",
        attachment_url=payload.attachment_url,
        related_ticket_id=payload.related_ticket_id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    uids = await _participant_ids(db, conversation_id)
    response = await _build_message_response(db, msg)

    try:
        await manager.broadcast(
            uids,
            {"event": "new_message", "message": response.model_dump(mode="json")},
        )
    except Exception as e:
        print(f"⚠️  WS broadcast failed (non-fatal): {e}")

    return response


# ============================================================
# UPLOAD FILE/IMAGE
# ============================================================
@router.post(
    "/conversations/{conversation_id}/upload",
    response_model=AttachmentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    conversation_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not FILE_SERVICE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="File uploads are disabled (file_service missing)",
        )

    await _assert_participant(db, conversation_id, current_user.id)

    info = await file_service.save_chat_attachment(file)

    msg = ChatMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=info["filename"],
        message_type="image" if info["is_image"] else "file",
        attachment_url=info["url"],
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    uids = await _participant_ids(db, conversation_id)
    response = await _build_message_response(db, msg)

    try:
        await manager.broadcast(
            uids,
            {"event": "new_message", "message": response.model_dump(mode="json")},
        )
    except Exception as e:
        print(f"⚠️  WS broadcast failed (non-fatal): {e}")

    return AttachmentUploadResponse(
        message=response,
        upload=UploadInfo(**info),
    )


# ============================================================
# MARK READ
# ============================================================
@router.post(
    "/conversations/{conversation_id}/read",
    response_model=MarkReadResponse,
)
async def mark_conversation_read(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    participant = await _assert_participant(db, conversation_id, current_user.id)
    participant.last_read_at = datetime.utcnow()
    await db.commit()
    return MarkReadResponse(message="Marked as read")


# ============================================================
# EDIT MESSAGE
# ============================================================
@router.put("/messages/{message_id}", response_model=ChatMessageResponse)
async def edit_message(
    message_id: int,
    payload: ChatMessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(ChatMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only edit your own messages")

    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")

    msg.content = payload.content
    msg.is_edited = True
    msg.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(msg)

    uids = await _participant_ids(db, msg.conversation_id)
    response = await _build_message_response(db, msg)

    try:
        await manager.broadcast(
            uids,
            {"event": "message_edited", "message": response.model_dump(mode="json")},
        )
    except Exception as e:
        print(f"⚠️  WS broadcast failed (non-fatal): {e}")

    return response


# ============================================================
# DELETE MESSAGE
# ============================================================
@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(ChatMessage, message_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.sender_id != current_user.id and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not allowed")

    msg.is_deleted = True
    msg.content = "[message deleted]"
    msg.attachment_url = None
    msg.updated_at = datetime.utcnow()
    await db.commit()

    uids = await _participant_ids(db, msg.conversation_id)
    try:
        await manager.broadcast(
            uids,
            {
                "event": "message_deleted",
                "message_id": msg.id,
                "conversation_id": msg.conversation_id,
            },
        )
    except Exception as e:
        print(f"⚠️  WS broadcast failed (non-fatal): {e}")

    return {"message": "Message deleted"}


# ============================================================
# ADD PARTICIPANT
# ============================================================
@router.post("/conversations/{conversation_id}/participants/{user_id}")
async def add_participant(
    conversation_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me = await _assert_participant(db, conversation_id, current_user.id)

    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.type != ConversationType.GROUP:
        raise HTTPException(status_code=400, detail="Not a group conversation")

    if not me.is_admin and current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only group admins can add members")

    existing = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User is already a participant")

    u = await db.get(User, user_id)
    if not u or not u.is_active:
        raise HTTPException(status_code=404, detail="User not found")

    db.add(
        ConversationParticipant(
            conversation_id=conversation_id,
            user_id=user_id,
            is_admin=False,
        )
    )
    await _create_system_message(
        db, conversation_id, f"{current_user.full_name} added {u.full_name}"
    )
    await db.commit()

    uids = await _participant_ids(db, conversation_id)
    try:
        await manager.broadcast(
            uids,
            {
                "event": "participant_added",
                "conversation_id": conversation_id,
                "user_id": user_id,
                "full_name": u.full_name,
            },
        )
    except Exception:
        pass

    return {"message": f"{u.full_name} added to group"}


# ============================================================
# REMOVE PARTICIPANT
# ============================================================
@router.delete("/conversations/{conversation_id}/participants/{user_id}")
async def remove_participant(
    conversation_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me = await _assert_participant(db, conversation_id, current_user.id)

    conv = await db.get(Conversation, conversation_id)
    if not conv or conv.type != ConversationType.GROUP:
        raise HTTPException(status_code=400, detail="Not a group conversation")

    if (
        user_id != current_user.id
        and not me.is_admin
        and current_user.role != UserRole.ADMIN
    ):
        raise HTTPException(
            status_code=403, detail="Only group admins can remove members"
        )

    result = await db.execute(
        select(ConversationParticipant).where(
            and_(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User is not a participant")

    u = await db.get(User, user_id)
    name = u.full_name if u else f"user {user_id}"

    await db.delete(target)
    await _create_system_message(
        db,
        conversation_id,
        f"{current_user.full_name} removed {name}"
        if user_id != current_user.id
        else f"{current_user.full_name} left the group",
    )
    await db.commit()

    uids = await _participant_ids(db, conversation_id) + [user_id]
    try:
        await manager.broadcast(
            uids,
            {
                "event": "participant_removed",
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
        )
    except Exception:
        pass

    return {"message": f"{name} removed from group"}


# ============================================================
# DELETE / ARCHIVE CONVERSATION
# ============================================================
@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me = await _assert_participant(db, conversation_id, current_user.id)

    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if (
        conv.created_by != current_user.id
        and not me.is_admin
        and current_user.role != UserRole.ADMIN
    ):
        raise HTTPException(status_code=403, detail="Not allowed")

    conv.is_active = False
    await db.commit()

    uids = await _participant_ids(db, conversation_id)
    try:
        await manager.broadcast(
            uids,
            {"event": "conversation_deleted", "conversation_id": conversation_id},
        )
    except Exception:
        pass

    return {"message": "Conversation archived"}