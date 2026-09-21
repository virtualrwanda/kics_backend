from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ============================================================
# USER MANAGEMENT
# ============================================================
class UserListResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    department: Optional[str] = None
    is_active: bool
    is_verified: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# PERFORMANCE
# ============================================================
class TechnicianPerformance(BaseModel):
    technician_id: int
    technician_name: str
    total_assigned: int
    total_resolved: int
    total_reopened: int
    avg_resolution_hours: float
    avg_first_response_minutes: float
    sla_compliance_percent: float
    avg_csat_rating: Optional[float] = None
    complaints_count: int
    rank: Optional[int] = None


# ============================================================
# DEADLINES / SLA
# ============================================================
class DeadlineItem(BaseModel):
    ticket_id: int
    ticket_number: Optional[str] = None
    title: str
    priority: str
    status: str
    assigned_to: Optional[str] = None
    resolution_deadline: datetime
    minutes_remaining: int
    is_overdue: bool
    is_escalated: bool


# ============================================================
# COMPLAINTS
# ============================================================
class ComplaintResponse(BaseModel):
    id: int
    ticket_id: int
    complaint_type: str
    description: str
    severity: str
    against_user: Optional[str] = None
    is_resolved: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# REPORTS
# ============================================================
class TicketVolumeReport(BaseModel):
    period: str
    total_created: int
    total_resolved: int
    total_closed: int
    total_reopened: int
    by_category: dict
    by_priority: dict
    by_status: dict


class SLAPolicyUpdate(BaseModel):
    first_response_minutes: int
    resolution_minutes: int
    is_active: bool = True


# ============================================================
# CUSTOM FIELDS
# ============================================================
class CustomFieldCreate(BaseModel):
    name: str
    label: str
    field_type: str = "text"          # text, number, select, checkbox, date, textarea
    options: Optional[List[str]] = None
    is_required: bool = False
    default_value: Optional[str] = None
    applies_to_category: Optional[str] = None
    display_order: int = 0


class CustomFieldUpdate(BaseModel):
    label: Optional[str] = None
    field_type: Optional[str] = None
    options: Optional[List[str]] = None
    is_required: Optional[bool] = None
    default_value: Optional[str] = None
    applies_to_category: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class CustomFieldResponse(BaseModel):
    id: int
    name: str
    label: str
    field_type: str
    options: Optional[List[str]] = None
    is_required: bool
    default_value: Optional[str] = None
    applies_to_category: Optional[str] = None
    display_order: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# BULK ACTIONS
# ============================================================
class BulkTicketAction(BaseModel):
    action: str                        # "assign" | "close" | "resolve" | "priority" | "category"
    ticket_ids: List[int]
    assigned_to: Optional[int] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    comment: Optional[str] = None