"""Pydantic models for Monthly Touch OS."""
from datetime import datetime
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, EmailStr, Field

from db import BaseDocument


# ===== USERS =====
class User(BaseDocument):
    email: EmailStr
    name: str
    role: Literal["admin", "manager"] = "manager"
    password_hash: str
    avatar_url: Optional[str] = None
    active: bool = True


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    avatar_url: Optional[str] = None


class RegisterIn(BaseModel):
    email: EmailStr
    name: str
    password: str
    role: Optional[Literal["admin", "manager"]] = "manager"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


# ===== CLIENTS =====
class Client(BaseDocument):
    name: str
    company: str
    industry: Optional[str] = None
    primary_contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    account_manager_id: Optional[str] = None
    account_manager_name: Optional[str] = None
    services: List[str] = Field(default_factory=list)  # e.g. SEO, GBP, Ads
    onboarding_date: Optional[str] = None
    mrr: Optional[float] = 0.0
    health_score: int = 75
    churn_risk: Literal["low", "medium", "high"] = "low"
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    notes: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Literal["active", "paused", "churned"] = "active"


class ClientIn(BaseModel):
    name: str
    company: str
    industry: Optional[str] = None
    primary_contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    account_manager_id: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    onboarding_date: Optional[str] = None
    mrr: Optional[float] = 0.0
    notes: Optional[str] = None
    avatar_url: Optional[str] = None


# ===== MEETINGS =====
class Win(BaseModel):
    title: str
    description: str
    metric: Optional[str] = None
    delta: Optional[str] = None


class Issue(BaseModel):
    title: str
    description: str
    action_plan: Optional[str] = None
    severity: Literal["low", "medium", "high"] = "medium"


class TalkingPoint(BaseModel):
    topic: str
    angle: str


class ActionItem(BaseDocument):
    meeting_id: Optional[str] = None
    client_id: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None  # account manager id/name
    owner_type: Literal["agency", "client"] = "agency"
    due_date: Optional[str] = None
    status: Literal["open", "in_progress", "completed", "blocked"] = "open"
    priority: Literal["low", "medium", "high"] = "medium"
    pushed_to: Optional[str] = None  # "clickup" | "ghl"


class ActionItemIn(BaseModel):
    client_id: str
    meeting_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    owner_type: Optional[Literal["agency", "client"]] = "agency"
    due_date: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = "medium"


class ContentCapture(BaseDocument):
    meeting_id: Optional[str] = None
    client_id: str
    type: Literal["testimonial_video", "testimonial_written", "quote", "case_study_lead", "clip"] = "quote"
    content: str
    sentiment_score: Optional[float] = None
    timestamp_in_meeting: Optional[str] = None
    requested: bool = False
    received: bool = False
    routed_to_marketing: bool = False
    notes: Optional[str] = None


class ContentCaptureIn(BaseModel):
    client_id: str
    meeting_id: Optional[str] = None
    type: Literal["testimonial_video", "testimonial_written", "quote", "case_study_lead", "clip"] = "quote"
    content: str
    requested: bool = False
    received: bool = False
    notes: Optional[str] = None


class Meeting(BaseDocument):
    client_id: str
    client_name: Optional[str] = None
    account_manager_id: Optional[str] = None
    account_manager_name: Optional[str] = None
    title: str
    scheduled_at: Optional[str] = None
    status: Literal["scheduled", "prep", "in_progress", "completed", "cancelled"] = "scheduled"
    google_meet_url: Optional[str] = None
    duration_minutes: int = 60

    # Auto-generated brief
    brief_generated_at: Optional[str] = None
    brief_model: Optional[str] = None
    wins: List[Win] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)
    talking_points: List[TalkingPoint] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)
    testimonial_opportunity: Optional[str] = None
    strategic_recommendations: List[str] = Field(default_factory=list)
    health_signal: Optional[str] = None

    # KPI snapshot used to generate the brief
    kpi_snapshot: Dict[str, Any] = Field(default_factory=dict)

    # During / post meeting
    notes: Optional[str] = None
    transcript: Optional[str] = None
    transcript_analyzed_at: Optional[str] = None
    sentiment: Optional[Literal["positive", "neutral", "negative"]] = None
    sentiment_summary: Optional[str] = None
    recap_html: Optional[str] = None
    recap_email: Optional[str] = None

    # Scorecard
    meeting_score: Optional[int] = None
    checklist: Dict[str, bool] = Field(default_factory=dict)


class MeetingIn(BaseModel):
    client_id: str
    title: str
    scheduled_at: Optional[str] = None
    google_meet_url: Optional[str] = None
    duration_minutes: Optional[int] = 60


class MeetingPatch(BaseModel):
    title: Optional[str] = None
    scheduled_at: Optional[str] = None
    google_meet_url: Optional[str] = None
    duration_minutes: Optional[int] = None
    status: Optional[Literal["scheduled", "prep", "in_progress", "completed", "cancelled"]] = None
    notes: Optional[str] = None
    transcript: Optional[str] = None
    checklist: Optional[Dict[str, bool]] = None
    meeting_score: Optional[int] = None


# ===== INTEGRATIONS =====
class Integration(BaseDocument):
    platform: str  # e.g. clickup, gohighlevel
    label: str
    status: Literal["not_connected", "connected", "error", "coming_soon"] = "not_connected"
    last_synced_at: Optional[str] = None
    last_error: Optional[str] = None
    credentials_encrypted: Dict[str, str] = Field(default_factory=dict)  # encrypted values
    metadata: Dict[str, Any] = Field(default_factory=dict)  # non-secret config (ids, urls)


class IntegrationConfigureIn(BaseModel):
    credentials: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ===== AI GENERATE =====
class GenerateBriefIn(BaseModel):
    model: Optional[str] = "claude-sonnet-4-6"  # claude-sonnet-4-6 | gpt-5.2 | gemini-3.1-pro-preview
    extra_context: Optional[str] = None


class AnalyzeTranscriptIn(BaseModel):
    transcript: str
    model: Optional[str] = "claude-sonnet-4-6"


class GenerateRecapIn(BaseModel):
    model: Optional[str] = "claude-sonnet-4-6"
