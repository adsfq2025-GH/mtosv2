"""Monthly Touch OS — backend API regression tests.

Covers: auth, dashboard, clients CRUD, meetings + AI (brief/transcript/recap),
action items, content captures, integrations (catalog/status/configure/test/disconnect),
docs, ai/models.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8000").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@monthlytouchos.com"
ADMIN_PASSWORD = "ChangeMe!2026"

# Long timeout for AI endpoints
AI_TIMEOUT = 90
DEFAULT_TIMEOUT = 30


# ----------------- shared state -----------------
state = {
    "token": None,
    "user": None,
    "client_id": None,
    "meeting_id": None,
    "action_item_ids": [],
    "content_capture_ids": [],
}


def auth_headers():
    return {"Authorization": f"Bearer {state['token']}", "Content-Type": "application/json"}


# ========== AUTH ==========
def test_health():
    r = requests.get(f"{API}/", timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_login_bootstrap_admin():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, f"login failed: {r.text}"
    data = r.json()
    assert "token" in data and isinstance(data["token"], str) and len(data["token"]) > 10
    assert data["user"]["email"] == ADMIN_EMAIL
    assert data["user"]["role"] == "admin"
    state["token"] = data["token"]
    state["user"] = data["user"]


def test_login_invalid_credentials():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 401


def test_register_duplicate_email():
    r = requests.post(
        f"{API}/auth/register",
        json={"email": ADMIN_EMAIL, "name": "Dup", "password": "Test12345!"},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 409


def test_register_second_user_is_manager():
    unique = f"TEST_user_{uuid.uuid4().hex[:6]}@example.com"
    r = requests.post(
        f"{API}/auth/register",
        json={"email": unique, "name": "TEST Manager", "password": "Test12345!"},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["role"] == "manager"
    assert "token" in data


def test_auth_me():
    r = requests.get(f"{API}/auth/me", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


def test_auth_me_no_token():
    r = requests.get(f"{API}/auth/me", timeout=DEFAULT_TIMEOUT)
    assert r.status_code in (401, 403)


# ========== DASHBOARD ==========
def test_dashboard_overview():
    r = requests.get(f"{API}/dashboard/overview", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    for k in [
        "total_clients", "avg_health_score", "churn_risk_high", "churn_risk_medium",
        "meetings_this_month", "open_action_items", "overdue_action_items",
        "content_captures_total", "content_pending_routing",
        "recent_meetings", "top_health_clients", "at_risk_clients",
    ]:
        assert k in data, f"missing key: {k}"
    assert isinstance(data["recent_meetings"], list)


def test_dashboard_requires_auth():
    r = requests.get(f"{API}/dashboard/overview", timeout=DEFAULT_TIMEOUT)
    assert r.status_code in (401, 403)


# ========== CLIENTS CRUD ==========
def test_create_client():
    payload = {
        "name": "TEST Sam Acme",
        "company": "TEST Acme Plumbing Co",
        "industry": "Plumbing",
        "primary_contact": "Sam Acme",
        "email": "sam@acme.test",
        "phone": "555-0100",
        "location": "Austin, TX",
        "services": ["SEO", "GBP", "Google Ads"],
        "mrr": 4500.0,
        "notes": "TEST seeded client",
    }
    r = requests.post(f"{API}/clients", headers=auth_headers(), json=payload, timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == payload["name"]
    assert data["company"] == payload["company"]
    assert data["mrr"] == 4500.0
    assert data["health_score"] == 75
    assert "id" in data
    state["client_id"] = data["id"]


def test_list_clients_includes_created():
    r = requests.get(f"{API}/clients", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert any(c["id"] == state["client_id"] for c in arr)


def test_get_client():
    r = requests.get(f"{API}/clients/{state['client_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    assert r.json()["id"] == state["client_id"]


def test_get_client_not_found():
    r = requests.get(f"{API}/clients/nope-{uuid.uuid4()}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 404


def test_patch_client():
    r = requests.patch(
        f"{API}/clients/{state['client_id']}",
        headers=auth_headers(),
        json={"notes": "TEST updated note", "mrr": 5000.0},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["notes"] == "TEST updated note"
    assert data["mrr"] == 5000.0


# ========== MEETINGS ==========
def test_create_meeting():
    payload = {
        "client_id": state["client_id"],
        "title": "TEST Monthly Touch — January",
        "scheduled_at": "2026-01-15T15:00:00+00:00",
        "google_meet_url": "https://meet.google.com/test-abc-xyz",
        "duration_minutes": 60,
    }
    r = requests.post(f"{API}/meetings", headers=auth_headers(), json=payload, timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["client_id"] == state["client_id"]
    assert data["title"] == payload["title"]
    assert data["status"] == "scheduled"
    state["meeting_id"] = data["id"]


def test_get_meeting():
    r = requests.get(f"{API}/meetings/{state['meeting_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    assert r.json()["id"] == state["meeting_id"]


def test_list_meetings_by_client():
    r = requests.get(f"{API}/meetings?client_id={state['client_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert any(m["id"] == state["meeting_id"] for m in arr)


# ========== AI: BRIEF ==========
def test_generate_brief_default_model():
    r = requests.post(
        f"{API}/meetings/{state['meeting_id']}/generate-brief",
        headers=auth_headers(),
        json={"model": "claude-sonnet-4-6", "extra_context": "Client has been with us 8 months. Strong NPS."},
        timeout=AI_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    # Persisted on meeting
    assert isinstance(data.get("wins"), list)
    assert isinstance(data.get("issues"), list)
    assert len(data["wins"]) >= 1, f"expected at least 1 win, got {len(data['wins'])}: {data['wins']}"
    assert len(data["issues"]) >= 0
    assert isinstance(data.get("talking_points"), list) and len(data["talking_points"]) > 0
    assert isinstance(data.get("suggested_questions"), list) and len(data["suggested_questions"]) > 0
    assert isinstance(data.get("strategic_recommendations"), list)
    assert data.get("testimonial_opportunity")
    assert data.get("health_signal")
    assert data.get("kpi_snapshot") and "google_business_profile" in data["kpi_snapshot"]
    assert data.get("brief_model") == "claude-sonnet-4-6"
    assert data.get("status") == "prep"


# ========== AI: ANALYZE TRANSCRIPT ==========
TRANSCRIPT = """
Account Manager: Hi Sam, great to see you again for our January Monthly Touch. How's January treating Acme Plumbing?
Sam (Client): Honestly fantastic. The phones have been ringing off the hook. We saw something like 184 calls last month from Google Business Profile alone — that's up almost 30 percent over December.
AM: That's a 28% MoM lift, exactly. And direction requests are also up about 14%. Your team's review velocity is helping a lot — you're sitting at a 4.8 average now.
Sam: Yeah, the guys love seeing those reviews. It's a real morale boost. Honestly, you all have transformed how we get leads. I was telling my wife last week that hiring your agency was probably the best business decision I made in 2025.
AM: Wow, that means a lot. Would you be open to sharing that on camera as a short testimonial sometime in February?
Sam: For sure, send me a calendar invite, I'd be happy to do it.
AM: Amazing. On the issues side, we did see one Google Ads ad group with CPL above target — we paused it last night and are restructuring the campaign. Should have it back live this week with better targeting.
Sam: Sounds good. While we're at it, can you guys help us figure out the website? I think the contact form is broken on mobile.
AM: I'll have our dev check that today and report back by Friday. I'll create a ticket.
Sam: Perfect. Also — we're opening a second location in Round Rock in March. I'll need GBP setup and probably a separate ad campaign for that area.
AM: Great news. I'll prep a scope and proposal for you by next Monday — Jan 22. We can review it on our next call.
Sam: Awesome. Honestly the local rank tracking has been impressive too — we went from rank 5.7 to 4.2 on the grid.
AM: That's a huge improvement. The team will be thrilled to hear it. We'll keep pushing on the local SEO front.
Sam: Thanks again, you all are killing it.
AM: Talk to you next month.
""".strip()


def test_analyze_transcript():
    r = requests.post(
        f"{API}/meetings/{state['meeting_id']}/analyze-transcript",
        headers=auth_headers(),
        json={"transcript": TRANSCRIPT, "model": "claude-sonnet-4-6"},
        timeout=AI_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "analysis" in data
    analysis = data["analysis"]
    assert analysis.get("sentiment") in ("positive", "neutral", "negative")
    # Should detect positive sentiment given the transcript
    assert analysis.get("sentiment") == "positive", f"expected positive, got {analysis.get('sentiment')}"
    assert isinstance(analysis.get("action_items"), list) and len(analysis["action_items"]) > 0
    assert isinstance(analysis.get("content_opportunities"), list)
    # Side effects: action items + content captures created
    assert len(data["created_action_items"]) > 0
    state["action_item_ids"] = [a["id"] for a in data["created_action_items"]]
    state["content_capture_ids"] = [c["id"] for c in data.get("created_content_captures", [])]


def test_meeting_sentiment_persisted():
    r = requests.get(f"{API}/meetings/{state['meeting_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    m = r.json()
    assert m.get("sentiment") == "positive"
    assert m.get("transcript_analyzed_at")
    assert m.get("transcript")


def test_client_health_updated_after_transcript():
    r = requests.get(f"{API}/clients/{state['client_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    c = r.json()
    assert c.get("sentiment") == "positive"
    assert isinstance(c.get("health_score"), int)


# ========== ACTION ITEMS ==========
def test_list_action_items_for_meeting():
    r = requests.get(
        f"{API}/action-items?meeting_id={state['meeting_id']}",
        headers=auth_headers(),
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200
    arr = r.json()
    assert len(arr) >= 1
    assert all(a["meeting_id"] == state["meeting_id"] for a in arr)


def test_patch_action_item_status():
    if not state["action_item_ids"]:
        pytest.skip("no action items")
    aid = state["action_item_ids"][0]
    r = requests.patch(
        f"{API}/action-items/{aid}",
        headers=auth_headers(),
        json={"status": "in_progress"},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"


def test_delete_action_item():
    if not state["action_item_ids"]:
        pytest.skip("no action items")
    aid = state["action_item_ids"][-1]
    r = requests.delete(f"{API}/action-items/{aid}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200


# ========== CONTENT CAPTURES ==========
def test_list_content_captures():
    r = requests.get(f"{API}/content-captures", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert isinstance(arr, list)


def test_patch_content_capture_routed():
    if not state["content_capture_ids"]:
        pytest.skip("no content captures created")
    cid = state["content_capture_ids"][0]
    r = requests.patch(
        f"{API}/content-captures/{cid}",
        headers=auth_headers(),
        json={"routed_to_marketing": True},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200
    assert r.json()["routed_to_marketing"] is True


# ========== AI: RECAP ==========
def test_generate_recap():
    r = requests.post(
        f"{API}/meetings/{state['meeting_id']}/generate-recap",
        headers=auth_headers(),
        json={"model": "claude-sonnet-4-6"},
        timeout=AI_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("subject")
    assert data.get("html")
    assert data.get("plain")


# ========== INTEGRATIONS ==========
def test_integrations_catalog():
    r = requests.get(f"{API}/integrations/catalog", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert len(arr) == 13, f"expected 13, got {len(arr)}"
    platforms = {x["platform"] for x in arr}
    for p in ["clickup", "gohighlevel", "google_ads", "google_business_profile",
              "google_analytics", "google_search_console", "ahrefs", "meta_ads",
              "google_lsa", "google_drive", "gmail", "google_meet", "map_checkins"]:
        assert p in platforms, f"missing {p}"


def test_integrations_status():
    r = requests.get(f"{API}/integrations", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert len(arr) == 13
    for item in arr:
        assert "status" in item
        assert "platform" in item


def test_integration_configure_clickup():
    r = requests.post(
        f"{API}/integrations/clickup/configure",
        headers=auth_headers(),
        json={"credentials": {"api_token": "TEST_pk_abc_123_token"}, "metadata": {"team_id": "TEST_team_999"}},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["platform"] == "clickup"
    assert data["status"] == "connected"


def test_integration_test_clickup():
    r = requests.post(f"{API}/integrations/clickup/test", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "connected"


def test_integration_status_after_configure():
    r = requests.get(f"{API}/integrations", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    clickup = next(x for x in arr if x["platform"] == "clickup")
    assert clickup["status"] == "connected"
    assert "api_token" in clickup.get("configured_field_keys", [])
    # ensure secrets not exposed
    assert "credentials_encrypted" not in clickup


def test_integration_configure_unknown_platform():
    r = requests.post(
        f"{API}/integrations/unknown_platform/configure",
        headers=auth_headers(),
        json={"credentials": {"k": "v"}},
        timeout=DEFAULT_TIMEOUT,
    )
    assert r.status_code == 404


def test_integration_disconnect_clickup():
    r = requests.delete(f"{API}/integrations/clickup", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200


# ========== DOCS ==========
def test_docs_list():
    r = requests.get(f"{API}/docs", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "items" in data and "categories" in data
    assert isinstance(data["items"], list) and len(data["items"]) >= 14
    slugs = {d["slug"] for d in data["items"]}
    assert "mtm-framework" in slugs


def test_docs_detail_mtm_framework():
    r = requests.get(f"{API}/docs/mtm-framework", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    data = r.json()
    assert data.get("body") and len(data["body"]) > 100
    assert data.get("slug") == "mtm-framework"


def test_docs_detail_not_found():
    r = requests.get(f"{API}/docs/nonexistent-slug", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 404


# ========== AI MODELS ==========
def test_ai_models():
    r = requests.get(f"{API}/ai/models", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    arr = r.json()
    assert len(arr) == 3
    keys = {m["key"] for m in arr}
    assert keys == {"claude-sonnet-4-6", "gpt-5.2", "gemini-3.1-pro-preview"}


# ========== CLEANUP ==========
def test_zz_delete_meeting():
    r = requests.delete(f"{API}/meetings/{state['meeting_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200


def test_zz_delete_client_admin():
    r = requests.delete(f"{API}/clients/{state['client_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert r.status_code == 200
    # Verify it's gone
    g = requests.get(f"{API}/clients/{state['client_id']}", headers=auth_headers(), timeout=DEFAULT_TIMEOUT)
    assert g.status_code == 404
