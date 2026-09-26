# Phase 8 — Production Cutover and Render Fallback

This document is a QA/operations gate. It does not authorize a production cutover by itself.

## Target architecture

- Vercel: frontend + FastAPI execution
- Supabase: database, authentication, persistent job state, scheduled jobs
- Render: temporary API fallback during the observation period
- Durable worker: disabled unless a future paid/background-worker decision is made

## Cutover rule

Do not turn Render off until all gates below have passed over multiple real production cycles.

### Required production-cycle evidence

1. Scheduled jobs
   - daily discovery succeeds
   - calendar generation succeeds
   - retention succeeds
   - no duplicate scheduled execution
2. Content generation
   - manual generation works
   - automatic daily content works
   - generated content is isolated to the correct user
3. Dashboard
   - dashboard loads repeatedly
   - Approved / Awaiting Approval / Published counts match database truth
   - counts are not affected by recent-post retention
4. Approvals
   - approve, edit, reject, regenerate
   - approved content remains durable across retries
   - failed LinkedIn publication remains retryable
5. LinkedIn
   - OAuth connect succeeds
   - whitelist enforcement works
   - text-only publish succeeds
   - image upload + publish succeeds
   - duplicate publish attempts remain idempotent
   - publish confirmation contains durable publication details
6. Retention
   - old content/memory is compacted according to policy
   - lifetime workflow counts remain unchanged
7. Multi-user isolation
   - one user cannot read, edit, approve, publish, or count another user's records
8. Reliability
   - Vercel frontend remains healthy
   - Supabase remains the source of truth
   - Render fallback can be reached when intentionally tested

## Render observation period

Keep Render available for a defined observation period after the Vercel + Supabase production cutover. Record:

- date/time of each scheduled cycle
- job result
- content generation result
- dashboard/count verification
- approval workflow verification
- LinkedIn publish verification
- retention verification
- multi-user isolation verification
- any Render fallback invocation

The observation period should cover multiple daily cycles rather than a single successful run.

## Render OFF procedure

Only after every gate is green:

1. Freeze the current production commit.
2. Confirm the Vercel project uses the repository root so both Next.js and FastAPI deploy together.
3. Confirm Vercel points at that commit.
4. Confirm Supabase migrations and cron jobs are healthy and the cron target is Vercel.
5. Confirm the latest production database counts.
6. Confirm no pending workflow operation depends on Render-specific state.
7. Disable Render traffic/fallback.
8. Monitor Vercel and Supabase for the next scheduled cycles.
9. Keep the Render deployment recoverable until the cutover has been accepted.

If any required gate fails, restore Render fallback and investigate before attempting the cutover again.

## Rollback principle

The first rollback target is the previous known-good Vercel/API release, not deletion of Supabase data. Supabase persistent state and scheduled jobs must remain intact throughout the cutover.
