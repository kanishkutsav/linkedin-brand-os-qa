-- Phase 2: durable scheduling definitions.
-- QA artifact only. Do not apply to production until the Render endpoint,
-- shared job key, and Vault secrets have been configured and verified.
-- Required Vault secrets: brand_os_render_url, brand_os_job_key.
-- pg_cron uses UTC. 09:00 IST = 03:30 UTC; 09:15 IST = 03:45 UTC.

select cron.schedule(
  'brand-os-daily-discovery',
  '30 3 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_render_url') || '/api/internal/scheduled-jobs/discovery',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron')
  )$$
);

select cron.schedule(
  'brand-os-calendar-generation',
  '45 3 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_render_url') || '/api/internal/scheduled-jobs/calendar',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron')
  )$$
);

select cron.schedule(
  'brand-os-daily-retention',
  '0 4 * * *',
  $$select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_render_url') || '/api/internal/scheduled-jobs/retention',
    headers := jsonb_build_object('Content-Type', 'application/json', 'X-Brand-OS-Job-Key', (select decrypted_secret from vault.decrypted_secrets where name = 'brand_os_job_key')),
    body := jsonb_build_object('source', 'supabase_cron')
  )$$
);
