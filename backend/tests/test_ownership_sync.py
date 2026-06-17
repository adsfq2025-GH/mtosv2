from ownership_sync import extract_account_manager_name, _normalize_custom_field_id


def test_normalize_custom_field_id_strips_cf_prefix():
    assert _normalize_custom_field_id("cf_98e55458-72fd-4b13-a753-694272346ddd") == "98e55458-72fd-4b13-a753-694272346ddd"


def test_extract_account_manager_name_uses_matching_custom_field_id():
    task = {
        "custom_fields": [
            {
                "id": "98e55458-72fd-4b13-a753-694272346ddd",
                "value": {"full_name": "Ariana Cole"},
            }
        ],
        "assignees": [{"username": "fallback-user"}],
    }
    assert (
        extract_account_manager_name(task, "cf_98e55458-72fd-4b13-a753-694272346ddd")
        == "Ariana Cole"
    )

