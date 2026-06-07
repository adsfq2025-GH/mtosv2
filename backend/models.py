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
    password_hash: str = ""
    avatar_url: Optional[str] = None
    active: bool = True
    auth_provider: Literal["local", "google"] = "local"
    google_sub: Optional[str] = None


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


class GoogleLoginIn(BaseModel):
    credential: str


# ===== TENANTS / WHITE LABEL =====
class Tenant(BaseDocument):
    slug: str
    name: str
    status: Literal["active", "suspended"] = "active"


class TenantMembership(BaseDocument):
    tenant_id: str
    user_id: str
    role: Literal["owner", "admin", "member", "viewer"] = "member"
    status: Literal["active", "invited", "disabled"] = "active"


class TenantSettings(BaseDocument):
    tenant_id: str
    branding: Dict[str, Any] = Field(default_factory=dict)
    terminology: Dict[str, Any] = Field(default_factory=dict)
    workflows: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)


class TenantSettingsIn(BaseModel):
    branding: Dict[str, Any] = Field(default_factory=dict)
    terminology: Dict[str, Any] = Field(default_factory=dict)
    workflows: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)


class PromptTemplate(BaseDocument):
    tenant_id: Optional[str] = None
    key: str
    text: str
    updated_at: Optional[str] = None


class PromptTemplateIn(BaseModel):
    text: str


# ===== CLIENTS =====
class Client(BaseDocument):
    tenant_id: Optional[str] = None
    name: str
    company: str
    industry: Optional[str] = None
    primary_contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    account_manager_id: Optional[str] = None
    account_manager_name: Optional[str] = None
    services: List[str] = Field(default_factory=list)  # e.g. SEO, GBP, Ads
    assigned_products: List[str] = Field(default_factory=list)
    crm_data: Dict[str, Any] = Field(default_factory=dict)
    gbp_data: Dict[str, Any] = Field(default_factory=dict)
    onboarding_date: Optional[str] = None
    mrr: Optional[float] = 0.0
    health_score: int = 75
    churn_risk: Literal["low", "medium", "high"] = "low"
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    notes: Optional[str] = None
    avatar_url: Optional[str] = None
    status: Literal["active", "paused", "churned"] = "active"
    suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    suggestions_generated_at: Optional[str] = None
    suggestions_model: Optional[str] = None
    feedback_alert: Optional[bool] = False
    feedback_alert_level: Optional[Literal["low", "medium", "high"]] = "low"
    feedback_alert_reason: Optional[str] = None
    feedback_last_submitted_at: Optional[str] = None
    feedback_rolling_avg: Dict[str, float] = Field(default_factory=dict)
    health_alert: Optional[bool] = False
    health_alert_level: Optional[Literal["low", "medium", "high"]] = "low"
    health_alert_reason: Optional[str] = None
    churn_risk_score: Optional[int] = 0
    churn_risk_indicators: List[str] = Field(default_factory=list)
    nps_rolling_avg: Optional[float] = None
    sentiment_rolling: Dict[str, int] = Field(default_factory=dict)
    health_last_submitted_at: Optional[str] = None


class ClientIn(BaseModel):
    name: str
    company: str
    industry: Optional[str] = None
    primary_contact: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    account_manager_id: Optional[str] = None
    services: List[str] = Field(default_factory=list)
    assigned_products: List[str] = Field(default_factory=list)
    crm_data: Dict[str, Any] = Field(default_factory=dict)
    gbp_data: Dict[str, Any] = Field(default_factory=dict)
    onboarding_date: Optional[str] = None
    mrr: Optional[float] = 0.0
    notes: Optional[str] = None
    avatar_url: Optional[str] = None



class ImportGhlClientsIn(BaseModel):
    location_id: str
    contacts: List[dict] = Field(default_factory=list)
    contact_ids: List[str] = Field(default_factory=list)


class GhlLocationTokenIn(BaseModel):
    location_id: str
    token: str


# ===== AI VISIBILITY =====
class AiVisibilityConfig(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    market: str = ""
    market_override: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    brand_override: Optional[str] = None
    domain_override: Optional[str] = None
    enabled: bool = True


class AiVisibilityConfigIn(BaseModel):
    market: str = ""
    market_override: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    brand_override: Optional[str] = None
    domain_override: Optional[str] = None
    enabled: bool = True


class AiVisibilityRun(BaseDocument):
    tenant_id: Optional[str] = None
    config_id: str
    client_id: str
    scan_id: Optional[str] = None
    market: str = ""
    keyword: str
    theme: Optional[str] = None
    prompt_kind: Optional[str] = None
    provider: Literal["openai", "gemini", "perplexity"]
    prompt: str
    response_text: str
    parsed: Dict[str, Any] = Field(default_factory=dict)
    hit: bool = False
    hit_brand: bool = False
    hit_domain: bool = False


class AiVisibilityScan(BaseDocument):
    tenant_id: Optional[str] = None
    config_id: str
    client_id: str
    scan_id: Optional[str] = None
    market: str = ""
    brand: str = ""
    domain: str = ""
    providers: Dict[str, Any] = Field(default_factory=dict)
    total: int = 0
    hits: int = 0
    overall_visibility_score: float = 0.0
    share_of_voice: Dict[str, Any] = Field(default_factory=dict)
    platform_rankings: Dict[str, Any] = Field(default_factory=dict)
    themes: List[Dict[str, Any]] = Field(default_factory=list)
    prompts_total: int = 0
    competitors: List[Dict[str, Any]] = Field(default_factory=list)
    content_intelligence: Dict[str, Any] = Field(default_factory=dict)
    growth_engine: Dict[str, Any] = Field(default_factory=dict)
    territory_intelligence: Dict[str, Any] = Field(default_factory=dict)
    data_confidence: Dict[str, Any] = Field(default_factory=dict)


# ===== MEETINGS =====
class Win(BaseModel):
    title: str
    description: str
    metric: Optional[str] = None
    delta: Optional[str] = None
    explain: Dict[str, Any] = Field(default_factory=dict)


class Issue(BaseModel):
    title: str
    description: str
    action_plan: Optional[str] = None
    solutions: List[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"
    explain: Dict[str, Any] = Field(default_factory=dict)


class CampaignRecommendation(BaseModel):
    platform: Literal["seo", "google_ads", "meta_ads", "google_business_profile", "other"] = "other"
    campaign: Optional[str] = None
    priority: Literal["high", "medium", "low"] = "medium"
    recommendations: List[str] = Field(default_factory=list)
    explain: Dict[str, Any] = Field(default_factory=dict)


class TalkingPoint(BaseModel):
    topic: str
    angle: str


class ActionItem(BaseDocument):
    tenant_id: Optional[str] = None
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
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    last_reminded_at: Optional[str] = None
    reminder_count: int = 0


class ActionItemIn(BaseModel):
    client_id: str
    meeting_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    owner_type: Optional[Literal["agency", "client"]] = "agency"
    due_date: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = "medium"


class RoadmapItem(BaseModel):
    id: str
    week: int = 1
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    owner_type: Literal["agency", "client"] = "agency"
    due_date: Optional[str] = None
    status: Literal["open", "in_progress", "completed", "blocked"] = "open"
    priority: Literal["low", "medium", "high"] = "medium"
    action_item_id: Optional[str] = None


class RoadmapPlan(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    start_date: str
    weeks: int = 12
    items: List[RoadmapItem] = Field(default_factory=list)


class RoadmapPlanIn(BaseModel):
    start_date: Optional[str] = None
    items: List[RoadmapItem] = Field(default_factory=list)


class RoadmapItemIn(BaseModel):
    week: int = 1
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    owner_type: Optional[Literal["agency", "client"]] = "agency"
    due_date: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = "medium"
    meeting_id: Optional[str] = None
    create_action_item: bool = True


class RoadmapItemPatch(BaseModel):
    week: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    owner_type: Optional[Literal["agency", "client"]] = None
    due_date: Optional[str] = None
    status: Optional[Literal["open", "in_progress", "completed", "blocked"]] = None
    priority: Optional[Literal["low", "medium", "high"]] = None


class ContentCapture(BaseDocument):
    tenant_id: Optional[str] = None
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


class ReviewEvent(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    kind: Literal["requested", "received"] = "requested"
    count: int = 1
    occurred_on: str
    channel: Optional[Literal["sms", "email", "in_person", "other"]] = "other"
    source: Optional[Literal["manual", "gbp", "imported"]] = "manual"
    notes: Optional[str] = None
    meeting_id: Optional[str] = None


class ReviewEventIn(BaseModel):
    kind: Literal["requested", "received"] = "requested"
    count: int = 1
    occurred_on: str
    channel: Optional[Literal["sms", "email", "in_person", "other"]] = "other"
    notes: Optional[str] = None
    meeting_id: Optional[str] = None


class ClientReviewGoal(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    monthly_goal: int = 10
    updated_at: Optional[str] = None


class ClientReviewGoalIn(BaseModel):
    monthly_goal: int = 10


class ReviewMonthlySnapshot(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    month: str
    received: int = 0
    avg_rating: Optional[float] = None
    source: Optional[str] = "gbp"
    kpi_period_kind: Optional[str] = None
    kpi_period_current_end: Optional[str] = None


class DiscoveryQuestionTemplate(BaseDocument):
    tenant_id: Optional[str] = None
    kind: Literal["operational", "market"] = "operational"
    category: str
    question: str
    tags: List[str] = Field(default_factory=list)
    deliverables: List[str] = Field(default_factory=list)
    active: bool = True


class DiscoveryQuestionTemplateIn(BaseModel):
    kind: Literal["operational", "market"] = "operational"
    category: str
    question: str
    tags: List[str] = Field(default_factory=list)
    deliverables: List[str] = Field(default_factory=list)
    active: bool = True


class MeetingDiscoveryQuestion(BaseModel):
    id: str
    kind: Literal["operational", "market"] = "operational"
    category: str
    question: str
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: Optional[str] = None
    status: Literal["suggested", "asked", "skipped"] = "suggested"
    notes: Optional[str] = None


class MeetingFeedback(BaseModel):
    lead_quality: int
    campaign_quality: int
    satisfaction: int
    results: int
    notes: Optional[str] = None
    submitted_at: Optional[str] = None
    submitted_by: Optional[str] = None


class Meeting(BaseDocument):
    tenant_id: Optional[str] = None
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
    wins_library: List[Win] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)
    issues_library: List[Issue] = Field(default_factory=list)
    talking_points: List[TalkingPoint] = Field(default_factory=list)
    talking_points_library: List[TalkingPoint] = Field(default_factory=list)
    suggested_questions: List[str] = Field(default_factory=list)
    prep_checklist: List[str] = Field(default_factory=list)
    ace_up_the_sleeve: List[Dict[str, Any]] = Field(default_factory=list)
    testimonial_opportunity: Optional[str] = None
    strategic_recommendations: List[str] = Field(default_factory=list)
    campaign_recommendations: List[CampaignRecommendation] = Field(default_factory=list)
    health_signal: Optional[str] = None

    automation_draft: Dict[str, Any] = Field(default_factory=dict)
    automation_draft_generated_at: Optional[str] = None
    automation_approved_at: Optional[str] = None

    # KPI snapshot used to generate the brief
    kpi_snapshot: Dict[str, Any] = Field(default_factory=dict)

    # During / post meeting
    notes: Optional[str] = None
    transcript: Optional[str] = None
    transcript_source: Dict[str, Any] = Field(default_factory=dict)
    transcript_analyzed_at: Optional[str] = None
    sentiment: Optional[Literal["positive", "neutral", "negative"]] = None
    sentiment_summary: Optional[str] = None
    transcript_analysis: Dict[str, Any] = Field(default_factory=dict)
    transcript_analysis_by_model: Dict[str, Any] = Field(default_factory=dict)
    nps_score: Optional[int] = None
    sentiment_classification: Optional[Literal["happy", "neutral", "concerned", "at_risk"]] = None
    health_notes: Optional[str] = None
    recap_html: Optional[str] = None
    recap_email: Optional[str] = None
    recap_subject: Optional[str] = None
    recap_sent_at: Optional[str] = None

    # Scorecard
    meeting_score: Optional[int] = None
    checklist: Dict[str, bool] = Field(default_factory=dict)
    deliverable_reviews: Dict[str, Any] = Field(default_factory=dict)
    discovery_questions: List[MeetingDiscoveryQuestion] = Field(default_factory=list)
    feedback: Optional[MeetingFeedback] = None


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
    deliverable_reviews: Optional[Dict[str, Any]] = None
    discovery_questions: Optional[List[MeetingDiscoveryQuestion]] = None
    feedback: Optional[MeetingFeedback] = None
    nps_score: Optional[int] = None
    sentiment_classification: Optional[Literal["happy", "neutral", "concerned", "at_risk"]] = None
    health_notes: Optional[str] = None


# ===== INTEGRATIONS =====
class Integration(BaseDocument):
    tenant_id: Optional[str] = None
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


class UserOAuthToken(BaseDocument):
    tenant_id: Optional[str] = None
    user_id: str
    provider: str
    platform: str
    refresh_token_encrypted: str
    scopes: List[str] = Field(default_factory=list)
    account_email: Optional[str] = None


class ClientIntegrationBinding(BaseDocument):
    tenant_id: Optional[str] = None
    client_id: str
    platform: str
    enabled: bool = True
    external_ids: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


class ClientIntegrationBindingIn(BaseModel):
    enabled: Optional[bool] = True
    external_ids: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)


# ===== AI GENERATE =====
class GenerateBriefIn(BaseModel):
    model: Optional[str] = None
    extra_context: Optional[str] = None


class GenerateSuggestionsIn(BaseModel):
    model: Optional[str] = None
    extra_context: Optional[str] = None


class AnalyzeTranscriptIn(BaseModel):
    transcript: str
    model: Optional[str] = None
    models: List[str] = Field(default_factory=list)


class GenerateRecapIn(BaseModel):
    model: Optional[str] = None


# ===== TICKETS / QA =====
class Ticket(BaseDocument):
    tenant_id: Optional[str] = None
    meeting_id: str
    client_id: str
    department: str
    title: str
    description: Optional[str] = None
    priority: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "in_progress", "completed", "blocked"] = "open"
    external_id: Optional[str] = None
    external_url: Optional[str] = None


class TicketIn(BaseModel):
    meeting_id: str
    client_id: str
    department: str
    title: str
    description: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = "medium"


class QAScorecard(BaseDocument):
    tenant_id: Optional[str] = None
    meeting_id: str
    client_id: str
    account_manager_id: Optional[str] = None
    account_manager_name: Optional[str] = None
    total_score: int
    dimensions: Dict[str, Any] = Field(default_factory=dict)
    feedback: Optional[str] = None
