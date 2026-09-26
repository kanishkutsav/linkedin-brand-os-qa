-- Phase 6 rollback: remove only the lease fencing column/index.

drop index if exists public.durable_jobs_lease_token_idx;
alter table public.durable_jobs
    drop column if exists lease_token;
