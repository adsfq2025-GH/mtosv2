"""Metadata for all 13 platform integrations + seed demo KPI data."""
from typing import Dict, List, Any

# Each integration: {platform: {label, category, fields:[{key,label,secret,help}], doc_url}}
INTEGRATIONS: Dict[str, Dict[str, Any]] = {
    "google_oauth": {
        "label": "Google OAuth",
        "category": "Core",
        "icon": "GoogleLogo",
        "description": "OAuth client used for Connect Google (Ads, GBP, GSC, GA4, Meet, Drive, Gmail). Configure only if backend env vars are not set or need override.",
        "fields": [
            {"key": "client_id", "label": "OAuth Client ID", "secret": False},
            {"key": "client_secret", "label": "OAuth Client Secret", "secret": True},
            {"key": "redirect_uri", "label": "Redirect URI", "secret": False},
        ],
    },
    "clickup": {
        "label": "ClickUp",
        "category": "Project Management",
        "icon": "ClipboardText",
        "description": "Pull account activity, overdue tasks, ticket SLAs. Push action items. OAuth app settings are loaded from backend env vars.",
        "fields": [
            {"key": "api_token", "label": "Personal API Token", "secret": True, "help": "Optional. ClickUp Settings -> Apps -> API Token."},
            {"key": "team_id", "label": "Workspace / Team ID", "secret": False, "help": "Optional. Raw numeric ClickUp team/workspace id."},
            {"key": "client_health_tracker_list_id", "label": "Client Health Tracker List ID", "secret": False, "help": "Optional. Use the raw numeric list id only, not the composite browser segment."},
            {"key": "account_manager_custom_field_id", "label": "Account Manager Field ID", "secret": False, "help": "Optional. Raw custom field id only; if omitted, sync falls back to the first ClickUp assignee."},
        ],
    },
    "gohighlevel": {
        "label": "GoHighLevel",
        "category": "CRM",
        "icon": "Lightning",
        "description": "CRM pipelines, leads, communications, workflows.",
        "fields": [
            {"key": "api_key", "label": "API Key (Agency or Sub-Account)", "secret": True, "help": "Private Integration Token. If using Agency token, also set Company ID and pick client locations in the Client record."},
            {"key": "company_id", "label": "Company ID (Agency ID)", "secret": False, "help": "Required to look up locations under an Agency token."},
        ],
    },
    "google_ads": {
        "label": "Google Ads",
        "category": "Paid Media",
        "icon": "Megaphone",
        "description": "PPC metrics, conversions, budget pacing, optimization opportunities. OAuth is per account manager via Connect Google.",
        "fields": [
            {"key": "developer_token", "label": "Developer Token", "secret": True},
            {"key": "login_customer_id", "label": "Manager (MCC) Customer ID", "secret": False, "help": "Optional. If using an MCC, set the manager account ID for cross-account access."},
            {"key": "customer_id", "label": "Customer ID", "secret": False, "help": "e.g. 123-456-7890"},
        ],
    },
    "google_business_profile": {
        "label": "Google Business Profile",
        "category": "Local SEO",
        "icon": "MapPin",
        "description": "GBP calls, direction requests, reviews, local visibility. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "google_analytics": {
        "label": "Google Analytics 4",
        "category": "Analytics",
        "icon": "ChartLine",
        "description": "Traffic, conversions, attribution, engagement. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "google_search_console": {
        "label": "Google Search Console",
        "category": "SEO",
        "icon": "MagnifyingGlass",
        "description": "Organic keywords, CTR, impressions, indexing. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "ahrefs": {
        "label": "Ahrefs",
        "category": "SEO",
        "icon": "TreeStructure",
        "description": "Backlinks, organic keywords, competitor analysis.",
        "fields": [
            {"key": "api_key", "label": "API Key", "secret": True, "help": "Standard plan minimum"},
            {"key": "target", "label": "Target Domain", "secret": False},
        ],
    },
    "meta_ads": {
        "label": "Meta Ads",
        "category": "Paid Media",
        "icon": "FacebookLogo",
        "description": "Facebook/Instagram ads, retargeting, lead gen, creative insights.",
        "fields": [
            {"key": "app_id", "label": "App ID", "secret": True},
            {"key": "app_secret", "label": "App Secret", "secret": True},
            {"key": "access_token", "label": "Access Token", "secret": True},
            {"key": "ad_account_id", "label": "Ad Account ID", "secret": False, "help": "act_xxxxxxxxxx"},
        ],
    },
    "google_lsa": {
        "label": "Google LSA (Local Services Ads)",
        "category": "Paid Media",
        "icon": "Phone",
        "description": "LSA leads, calls, lead quality scoring. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "google_drive": {
        "label": "Google Drive",
        "category": "Documents",
        "icon": "FolderOpen",
        "description": "Onboarding forms, deliverables, photos, Google Meet recordings & transcripts. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "gmail": {
        "label": "Gmail",
        "category": "Communication",
        "icon": "Envelope",
        "description": "Communication history, unresolved threads, follow-up drafts. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "google_meet": {
        "label": "Google Meet",
        "category": "Meetings",
        "icon": "VideoCamera",
        "description": "Auto-pull Meet recordings and Gemini-generated transcripts from Drive. OAuth is per account manager via Connect Google.",
        "fields": [],
    },
    "google_calendar": {
        "label": "Google Calendar",
        "category": "Meetings",
        "icon": "CalendarCheck",
        "description": "Sync meetings to each account manager’s personal calendar via Connect Google.",
        "fields": [],
    },
    "map_checkins": {
        "label": "Map Check-ins",
        "category": "Local Rank Tracking",
        "icon": "MapTrifold",
        "description": "Geo-grid heat map rankings, local rank tracking, field tech check-ins.",
        "fields": [
            {"key": "api_base_url", "label": "API Base URL", "secret": False, "help": "e.g. https://api.mapcheckins.com"},
            {"key": "api_token", "label": "API Token", "secret": True},
            {"key": "company_id", "label": "Company / Workspace ID", "secret": False},
        ],
    },
}


def list_integrations() -> List[Dict[str, Any]]:
    out = []
    for platform, meta in INTEGRATIONS.items():
        # never expose secret-flag with secret values
        fields = [{k: v for k, v in f.items() if k != "value"} for f in meta["fields"]]
        out.append({
            "platform": platform,
            "label": meta["label"],
            "category": meta["category"],
            "icon": meta["icon"],
            "description": meta["description"],
            "fields": fields,
        })
    return out


# ---------- DEMO KPI SNAPSHOT (used when integrations not connected) ----------
def demo_kpi_snapshot(client_name: str = "") -> Dict[str, Any]:
    return {
        "period": "Last 30 days",
        "google_business_profile": {
            "calls": {"value": 184, "delta_pct": 28, "trend": "up"},
            "direction_requests": {"value": 312, "delta_pct": 14, "trend": "up"},
            "website_clicks": {"value": 426, "delta_pct": 9, "trend": "up"},
            "new_reviews": {"value": 7, "avg_rating": 4.8},
            "photo_views": {"value": 5810, "delta_pct": 22, "trend": "up"},
        },
        "map_checkins": {
            "avg_grid_rank": {"value": 4.2, "previous": 5.7, "delta": -1.5, "trend": "improved"},
            "top_3_pct": {"value": 41, "previous": 28, "delta_pct": 13},
            "keywords_improved": 14,
            "keywords_dropped": 3,
            "field_checkins": 38,
        },
        "google_search_console": {
            "impressions": {"value": 92410, "delta_pct": 18},
            "clicks": {"value": 3120, "delta_pct": 11},
            "avg_position": {"value": 12.4, "previous": 14.1, "trend": "improved"},
            "ctr_pct": {"value": 3.4, "previous": 3.0},
            "top_query_movers": [
                {"query": "emergency plumber near me", "change": "+6"},
                {"query": "24 hour plumbing", "change": "+4"},
            ],
        },
        "ahrefs": {
            "organic_keywords": {"value": 1284, "delta_pct": 8},
            "domain_rating": {"value": 38, "previous": 36},
            "referring_domains": {"value": 142, "new": 9},
            "competitor_gap": "Competitor X gained 12 backlinks from local directories",
        },
        "google_analytics": {
            "sessions": {"value": 8120, "delta_pct": 12},
            "conversions": {"value": 188, "delta_pct": 16},
            "conv_rate_pct": {"value": 2.3, "previous": 2.1},
            "engaged_sessions_pct": {"value": 61, "previous": 58},
        },
        "google_ads": {
            "spend": {"value": 4820, "delta_pct": 3},
            "leads": {"value": 67, "delta_pct": 22},
            "cpl": {"value": 71.9, "previous": 82.1, "trend": "improved"},
            "qualified_leads": 49,
            "issue": "1 ad group has CPL above target — paused tonight",
        },
        "meta_ads": {
            "spend": {"value": 1840, "delta_pct": 0},
            "leads": {"value": 31, "delta_pct": 14},
            "cpl": {"value": 59.4},
            "top_creative": "Before/After kitchen reel — 4.2x CTR vs account avg",
        },
        "google_lsa": {
            "leads": {"value": 22, "delta_pct": 18},
            "answered_calls_pct": 91,
            "avg_lead_cost": 28.5,
        },
        "gohighlevel": {
            "new_opportunities": 54,
            "won_value": 18400,
            "pipeline_value": 62800,
            "stalled_deals": 4,
            "sms_sent": 412,
            "email_sent": 1280,
        },
        "clickup": {
            "tasks_completed_last_30d": 42,
            "overdue": 3,
            "blocked": 1,
            "open_tickets": 6,
            "client_requests_pending": 2,
        },
        "gmail": {
            "threads_with_client": 28,
            "unanswered_threads": 1,
            "avg_response_hours": 4.1,
        },
        "reviews_reputation": {
            "new_reviews": 9,
            "avg_rating": 4.8,
            "responded_pct": 100,
        },
    }
