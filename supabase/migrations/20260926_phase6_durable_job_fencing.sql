-- Phase 6: durable worker lease fencing.
-- Additive only. Existing durable jobs remain claimable; active leases are
-- protected by a unique random token so a stale worker cannot finalize work
-- after its lease has been reclaimed.

alter table public.durable_jobs
    add column if not exists lease_token text;

create index if not exists durable_jobs_lease_token_idx
    on public.durable_jobs (lease_token);

