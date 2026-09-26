-- Phase 8: move Supabase scheduled HTTP dispatch from Render to the Vercel API.
-- QA artifact only. Before applying, create Vault secrets:
--   brand_os_vercel_url = the production Vercel origin
--   brand_os_job_key   = the shared internal scheduled-job key
-- Keep the existing Render URL secret until the observation period is complete.

select cron.unschedule('brand-os-daily-discovery');
select cron.unschedule('brand-os-calendar-generation');
select cron.unschedule('brand-os-daily-retention');
select cron.unschedule('brand-os-learning-processing');

select cron.schedule(
  'brand-os-daily-discovery',
  '30 3 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_vercel_url') || '/api/internal/scheduled-jobs/discovery',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron', 'execution_target', 'vercel')
  )$$
);

select cron.schedule(
  'brand-os-calendar-generation',
  '45 3 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_vercel_url') || '/api/internal/scheduled-jobs/calendar',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron', 'execution_target', 'vercel')
  )$$
);

select cron.schedule(
  'brand-os-daily-retention',
  '0 4 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_vercel_url') || '/api/internal/scheduled-jobs/retention',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron', 'execution_target', 'vercel')
  )$$
);


select cron.schedule(
  'brand-os-learning-processing',
  '*/15 * * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_vercel_url') || '/api/internal/scheduled-jobs/learning',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron', 'execution_target', 'vercel')
  )$$
);
