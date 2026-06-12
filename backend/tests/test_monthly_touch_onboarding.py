from monthly_touch import apply_first_90_day_brief_support, merge_brief_extra_context


def test_merge_brief_extra_context_joins_existing_and_onboarding_text():
    merged = merge_brief_extra_context("Existing note", "90-day roadmap note")
    assert merged == "Existing note\n\n90-day roadmap note"


def test_apply_first_90_day_brief_support_prepends_onboarding_items():
    brief = {
        "talking_points": [{"topic": "SEO", "angle": "Review rankings"}],
        "suggested_questions": ["What has felt strongest so far?"],
        "prep_checklist": ["Review KPI snapshot"],
        "strategic_recommendations": ["Improve GBP posting consistency"],
    }
    support = {
        "talking_point": {
            "topic": "First 90 Days Progress",
            "angle": "Review reviews, images, and check-ins.",
        },
        "suggested_questions": [
            "Have you been able to help us bring in the reviews we need?",
            "Can we line up fresh images and check-ins before the next meeting?",
        ],
        "prep_checklist": [
            "Review first-90-days roadmap progress: requested reviews, fresh images, and map check-ins before the client call."
        ],
        "strategic_recommendation": "Keep the 90-day onboarding roadmap active.",
    }

    updated = apply_first_90_day_brief_support(brief, support)

    assert updated["talking_points"][0]["topic"] == "First 90 Days Progress"
    assert updated["suggested_questions"][0] == "Have you been able to help us bring in the reviews we need?"
    assert updated["suggested_questions"][1] == "Can we line up fresh images and check-ins before the next meeting?"
    assert updated["prep_checklist"][0].startswith("Review first-90-days roadmap progress")
    assert updated["strategic_recommendations"][0] == "Keep the 90-day onboarding roadmap active."
