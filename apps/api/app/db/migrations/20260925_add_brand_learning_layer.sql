-- Brand Learning Layer: per-profile memory, event log, and semantic retrieval.
-- Additive only. Existing content, approval, research, and Brand DNA tables are untouched.

create extension if not exists vector with schema extensions;

create table if not exists public.learning_events (
    id bigserial primary key,
    profile_id integer not null references public.user_profiles(id) on delete cascade,
    event_type varchar(60) not null,
    source_type varchar(60) not null,
    source_id varchar(120),
    content text not null,
    metadata_json text,
    status varchar(30) not null default 'PENDING',
    attempts integer not null default 0,
    last_error text,
    embedding extensions.vector(768),
    created_at timestamptz not null default now(),
    processed_at timestamptz
);

create index if not exists idx_learning_events_profile_created
    on public.learning_events(profile_id, created_at desc);
create index if not exists idx_learning_events_pending
    on public.learning_events(status, created_at);
create index if not exists idx_learning_events_source
    on public.learning_events(profile_id, source_type, source_id);

create table if not exists public.learning_memories (
    id bigserial primary key,
    profile_id integer not null references public.user_profiles(id) on delete cascade,
    memory_key varchar(180) not null,
    memory_type varchar(50) not null,
    content text not null,
    confidence varchar(20) not null default 'medium',
    importance double precision not null default 0.5,
    source_count integer not null default 1,
    metadata_json text,
    embedding extensions.vector(768),
    first_observed_at timestamptz not null default now(),
    last_observed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(profile_id, memory_key)
);

create index if not exists idx_learning_memories_profile_updated
    on public.learning_memories(profile_id, updated_at desc);
create index if not exists idx_learning_memories_profile_type
    on public.learning_memories(profile_id, memory_type);

create index if not exists idx_learning_events_embedding_hnsw
    on public.learning_events using hnsw (embedding vector_cosine_ops);
create index if not exists idx_learning_memories_embedding_hnsw
    on public.learning_memories using hnsw (embedding vector_cosine_ops);

alter table public.learning_events enable row level security;
alter table public.learning_memories enable row level security;

revoke all on table public.learning_events from anon, authenticated;
revoke all on table public.learning_memories from anon, authenticated;

grant all on table public.learning_events to service_role;
grant all on table public.learning_memories to service_role;

create or replace function public.match_learning_events(
    p_profile_id integer,
    p_query_embedding extensions.vector(768),
    p_match_threshold double precision default 0.45,
    p_match_count integer default 8
)
returns table (
    id bigint,
    event_type varchar,
    source_type varchar,
    source_id varchar,
    content text,
    metadata_json text,
    created_at timestamptz,
    similarity double precision
)
language sql
stable
as $$
    select
        e.id,
        e.event_type,
        e.source_type,
        e.source_id,
        e.content,
        e.metadata_json,
        e.created_at,
        1 - (e.embedding <=> p_query_embedding) as similarity
    from public.learning_events e
    where e.profile_id = p_profile_id
      and e.embedding is not null
      and 1 - (e.embedding <=> p_query_embedding) >= p_match_threshold
    order by e.embedding <=> p_query_embedding asc
    limit least(greatest(p_match_count, 1), 50);
$$;

create or replace function public.match_learning_memories(
    p_profile_id integer,
    p_query_embedding extensions.vector(768),
    p_match_threshold double precision default 0.45,
    p_match_count integer default 8
)
returns table (
    id bigint,
    memory_key varchar,
    memory_type varchar,
    content text,
    confidence varchar,
    importance double precision,
    source_count integer,
    metadata_json text,
    updated_at timestamptz,
    similarity double precision
)
language sql
stable
as $$
    select
        m.id,
        m.memory_key,
        m.memory_type,
        m.content,
        m.confidence,
        m.importance,
        m.source_count,
        m.metadata_json,
        m.updated_at,
        1 - (m.embedding <=> p_query_embedding) as similarity
    from public.learning_memories m
    where m.profile_id = p_profile_id
      and m.embedding is not null
      and 1 - (m.embedding <=> p_query_embedding) >= p_match_threshold
    order by m.embedding <=> p_query_embedding asc
    limit least(greatest(p_match_count, 1), 50);
$$;

revoke all on function public.match_learning_events(integer, extensions.vector, double precision, integer) from public, anon, authenticated;
revoke all on function public.match_learning_memories(integer, extensions.vector, double precision, integer) from public, anon, authenticated;
grant execute on function public.match_learning_events(integer, extensions.vector, double precision, integer) to service_role;
grant execute on function public.match_learning_memories(integer, extensions.vector, double precision, integer) to service_role;
