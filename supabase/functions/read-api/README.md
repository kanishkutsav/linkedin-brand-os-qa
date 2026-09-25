# Brand OS read-api (Phase 4 QA)

Staged Supabase Edge Function for the Phase 4 read migration. It is source-only in QA and is not deployed to production.

It preserves the existing custom Brand OS bearer-token contract. The function hashes the token with SHA-256, validates auth_sessions and auth_users, then reads through Supabase using the service role. The service role is never accepted from callers or returned.

Routes:
- /read-api/profile
- /read-api/brand/status
- /read-api/brand/memory
- /read-api/brand/source-posts
- /read-api/dashboard/approvals
- /read-api/agent/status
- /read-api/research/opportunities
- /read-api/learning/status
- /read-api/analytics/overview

QA rollout: deploy only to an isolated QA Supabase environment, compare responses route-by-route against Render, then enable the Vercel read client behind a feature flag. Production deployment is intentionally out of scope.
