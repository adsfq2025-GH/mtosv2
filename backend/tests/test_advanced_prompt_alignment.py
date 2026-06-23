import asyncio

import ai


def test_generate_meeting_brief_limits_primary_wins_and_issues(monkeypatch):
    async def fake_run_chat(system: str, user_text: str, model_key: str, session_id: str | None):
        return "{}"

    async def fake_extract(_raw: str, _model_key: str, _session_id: str | None):
        return {
            "wins": [
                {"title": "Win 1", "description": "Desc 1", "explain": {"kpi_paths": ["google_business_profile.calls.value"]}},
                {"title": "Win 2", "description": "Desc 2", "explain": {"kpi_paths": ["google_business_profile.calls.value"]}},
                {"title": "Win 3", "description": "Desc 3", "explain": {"kpi_paths": ["google_business_profile.calls.value"]}},
                {"title": "Win 4", "description": "Desc 4", "explain": {"kpi_paths": ["google_business_profile.calls.value"]}},
            ],
            "issues": [
                {
                    "title": "Issue 1",
                    "description": "Issue desc 1",
                    "solutions": ["Already adjusting targeting"],
                    "explain": {"kpi_paths": ["google_ads.leads.value"]},
                },
                {
                    "title": "Issue 2",
                    "description": "Issue desc 2",
                    "solutions": [],
                    "explain": {"kpi_paths": ["google_ads.leads.value"]},
                },
                {
                    "title": "Issue 3",
                    "description": "Issue desc 3",
                    "solutions": ["Monitor closely"],
                    "explain": {"kpi_paths": ["google_ads.leads.value"]},
                },
            ],
        }

    monkeypatch.setattr(ai, "run_chat", fake_run_chat)
    monkeypatch.setattr(ai, "_extract_or_repair_json", fake_extract)

    brief = asyncio.run(
        ai.generate_meeting_brief(
            client={"name": "Acme"},
            kpi_snapshot={
                "google_business_profile": {"calls": {"value": 42}},
                "google_ads": {"leads": {"value": 12}},
            },
            extra_context="",
        )
    )

    assert len(brief["wins"]) == 3
    assert [item["title"] for item in brief["wins"]] == ["Win 1", "Win 2", "Win 3"]
    assert len(brief["issues"]) == 2
    assert brief["issues"][0]["action_plan"] == "Already adjusting targeting"
    assert "Active monitoring and follow-up on" in brief["issues"][1]["action_plan"]
