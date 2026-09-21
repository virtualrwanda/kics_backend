from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from ..models.ticket import TicketPriority, TicketStatus, TicketCategory


class TicketBase(BaseModel):
    title: str
    description: str
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM


class TicketCreate(TicketBase):
    pass


class TicketUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[TicketCategory] = None
    priority: Optional[TicketPriority] = None
    status: Optional[TicketStatus] = None
    assigned_to: Optional[int] = None
    resolution_notes: Optional[str] = None
    time_spent_minutes: Optional[int] = None


class TicketResponse(TicketBase):
    id: int
    ticket_number: Optional[str] = None
    status: TicketStatus
    created_by: int
    assigned_to: Optional[int] = None
    is_resolved: bool
    resolution_notes: Optional[str] = None
    time_spent_minutes: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
