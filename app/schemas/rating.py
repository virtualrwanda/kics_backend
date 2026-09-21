from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ============================================================
# RATE A TICKET
# ============================================================
class TicketRatingCreate(BaseModel):
    stars: int = Field(..., ge=1, le=5, description="Overall 1–5 stars")
    comment: Optional[str] = None
    speed_rating: Optional[int] = Field(None, ge=1, le=5)
    quality_rating: Optional[int] = Field(None, ge=1, le=5)
    communication_rating: Optional[int] = Field(None, ge=1, le=5)
    professionalism_rating: Optional[int] = Field(None, ge=1, le=5)


class TicketRatingResponse(BaseModel):
    id: int
    ticket_id: int
    technician_id: int
    technician_name: Optional[str] = None
    rater_id: int
    rater_name: Optional[str] = None
    stars: int
    speed_rating: Optional[int] = None
    quality_rating: Optional[int] = None
    communication_rating: Optional[int] = None
    professionalism_rating: Optional[int] = None
    comment: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# TECHNICIAN PERFORMANCE (self-view)
# ============================================================
class MyPerformance(BaseModel):
    technician_id: int
    technician_name: str
    total_rated: int
    avg_stars: float
    avg_speed: Optional[float] = None
    avg_quality: Optional[float] = None
    avg_communication: Optional[float] = None
    avg_professionalism: Optional[float] = None
    total_resolved: int
    avg_resolution_hours: float
    sla_compliance_percent: float
    rank: Optional[int] = None
    active_target: Optional["TechnicianTargetResponse"] = None


# ============================================================
# LEADERBOARD
# ============================================================
class LeaderboardEntry(BaseModel):
    rank: int
    technician_id: int
    technician_name: str
    avatar_url: Optional[str] = None
    total_resolved: int
    total_rated: int
    avg_stars: float
    avg_resolution_hours: float
    sla_compliance_percent: float
    complaints_count: int
    score: float  # composite score for ranking


# ============================================================
# TARGETS / SPRINTS
# ============================================================
class TechnicianTargetCreate(BaseModel):
    name: str
    start_date: datetime
    end_date: datetime
    target_resolved: int = 0
    target_csat_min: int = Field(0, ge=0, le=5)
    target_avg_hours_max: int = 0
    target_sla_percent: int = Field(0, ge=0, le=100)
    notes: Optional[str] = None


class TechnicianTargetUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    target_resolved: Optional[int] = None
    target_csat_min: Optional[int] = None
    target_avg_hours_max: Optional[int] = None
    target_sla_percent: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TechnicianTargetResponse(BaseModel):
    id: int
    technician_id: int
    technician_name: Optional[str] = None
    set_by: Optional[int] = None
    set_by_name: Optional[str] = None
    name: str
    start_date: datetime
    end_date: datetime
    target_resolved: int
    target_csat_min: int
    target_avg_hours_max: int
    target_sla_percent: int
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TechnicianProgress(BaseModel):
    technician_id: int
    technician_name: str
    target: TechnicianTargetResponse

    # Actual
    actual_resolved: int
    actual_avg_stars: float
    actual_avg_hours: float
    actual_sla_percent: float

    # Percent progress (0–100+)
    resolved_progress: float
    csat_progress: float
    time_progress: float
    sla_progress: float

    # Boolean achievements
    resolved_met: bool
    csat_met: bool
    time_met: bool
    sla_met: bool
    all_met: bool

    # Days remaining
    days_remaining: int


# Forward references
MyPerformance.model_rebuild()