from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean,
    ForeignKey, Enum, Index, UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from ..core.database import Base


class ConversationType(str, enum.Enum):
    DIRECT = "direct"   # 1-to-1
    GROUP = "group"     # multi-user


class Conversation(Base):
    """A DM (2 users) or group chat (N users)."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(
        Enum(ConversationType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=True)       # only for groups
    description = Column(Text, nullable=True)       # only for groups
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for auto-DMs
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    participants = relationship(
        "ConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "ChatMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_conversations_type_active", "type", "is_active"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ConversationParticipant(Base):
    """Who is in each conversation (DM or group)."""
    __tablename__ = "conversation_participants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_admin = Column(Boolean, default=False)      # can add/remove members in groups
    is_muted = Column(Boolean, default=False)
    last_read_at = Column(DateTime, nullable=True)  # for unread counts

    joined_at = Column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="participants")

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conv_user"),
        Index("ix_conv_part_user", "user_id", "conversation_id"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class ChatMessage(Base):
    """A single message in a conversation."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    content = Column(Text, nullable=False)
    message_type = Column(String(20), default="text")  # text, image, file
    attachment_url = Column(String(500), nullable=True)

    is_edited = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)

    # Optional: link a message to a ticket
    related_ticket_id = Column(
        Integer,
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, onupdate=func.now())

    conversation = relationship("Conversation", back_populates="messages")
    reads = relationship(
        "MessageRead",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_msg_conv_created", "conversation_id", "created_at"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )


class MessageRead(Base):
    """Tracks who has read which message (read receipts)."""
    __tablename__ = "message_reads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        Integer,
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at = Column(DateTime, server_default=func.now())

    message = relationship("ChatMessage", back_populates="reads")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_msg_user_read"),
        {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"},
    )