from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
FN=ROOT/"supabase/functions/write-api/index.ts"
MIG=ROOT/"supabase/migrations/20260926_phase5_mutation_idempotency.sql"
ROLL=ROOT/"supabase/migrations/20260926_phase5_mutation_idempotency_rollback.sql"
def test_write_runtime_post_only():
 t=FN.read_text();assert 'req.method!=="POST"' in t and "Deno.serve" in t and "SUPABASE_SERVICE_ROLE_KEY" in t
 assert 'from("auth_sessions")' in t and 'from("auth_users")' in t
def test_mutations_allowlisted():
 t=FN.read_text()
 for op in ("create-draft","learning-thought","approve","edit","reject"):assert op in t
def test_idempotency_required():
 t=FN.read_text();assert "X-Idempotency-Key" in t and "mutation_requests" in t
def test_guardrails_and_ownership_preserved():
 t=FN.read_text()
 for s in ("Em/en dashes are not allowed","Semicolons are not allowed","Content is too short","Too many hashtags"):assert s in t
 assert "content_items.profile_id" in t and "Approval not found" in t
def test_approval_status_contract():
 t=FN.read_text()
 for s in ("PENDING","EDITED","REGENERATED","APPROVED","EXECUTED","PUBLISHING","REJECTED"):assert s in t
def test_no_ai_or_linkedin():
 t=FN.read_text();assert "ModelRouterService" not in t and "fetch(" not in t
 assert "publish" not in t.lower()
def test_migration_scoped():
 t=MIG.read_text().lower();r=ROLL.read_text().lower()
 assert "create table if not exists public.mutation_requests" in t and "unique(user_id, operation, idempotency_key)" in t
 assert "drop table if exists public.mutation_requests" in r and "durable_jobs" not in r
