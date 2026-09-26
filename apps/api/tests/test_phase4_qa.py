from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FUNCTION = ROOT / "supabase" / "functions" / "read-api" / "index.ts"
EXPECTED = {"profile","brand/status","brand/memory","brand/source-posts","dashboard/approvals","agent/status","research/opportunities","learning/status","analytics/overview"}

def test_edge_function_exists_and_is_read_only():
    text = FUNCTION.read_text(encoding="utf-8")
    assert "Deno.serve" in text and 'req.method!=="GET"' in text
    assert "SUPABASE_SERVICE_ROLE_KEY" in text
    assert ".insert(" not in text and ".update(" not in text and ".upsert(" not in text and ".delete(" not in text and ".rpc(" not in text
    assert "POST" not in text

def test_explicit_route_allowlist():
    text = FUNCTION.read_text(encoding="utf-8")
    for route in EXPECTED:
        assert route in text

def test_custom_session_auth_is_preserved():
    text = FUNCTION.read_text(encoding="utf-8")
    assert 'from("auth_sessions")' in text and 'from("auth_users")' in text
    assert "SHA-256" in text and "is_whitelisted" in text and "is_active" in text

def test_dashboard_count_semantics_are_lifetime_status_based():
    text = FUNCTION.read_text(encoding="utf-8")
    for status in ("PENDING","EDITED","REGENERATED","APPROVED","EXECUTED","REJECTED","PUBLISHING"):
        assert status in text
    assert "awaiting_approval" in text and "published" in text

def test_user_scope_is_explicit():
    text = FUNCTION.read_text(encoding="utf-8")
    assert '.eq("profile_id", user.id)' in text
    assert "contentScope(user)" in text

def test_no_production_scheduler_or_deploy_logic():
    text = FUNCTION.read_text(encoding="utf-8")
    assert "cron.schedule" not in text
    assert "deploy" not in text.lower()
