-- tubeInsight-ai Day 3. Run as project owner after 001_create_videos.sql.
begin;

create table if not exists public.chat_sessions (
    id uuid primary key default gen_random_uuid(),
    video_id text not null references public.videos(video_id) on delete cascade,
    next_sequence bigint not null default 0 check (next_sequence >= 0),
    revision bigint not null default 0 check (revision >= 0),
    lease_token uuid,
    lease_until timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create table if not exists public.chat_messages (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.chat_sessions(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null check (length(btrim(content)) > 0 and octet_length(content) <= 40000),
    sequence_number bigint not null check (sequence_number >= 0),
    created_at timestamptz not null default now(),
    unique(session_id, sequence_number)
);
create index if not exists chat_sessions_video_id_idx on public.chat_sessions(video_id);
create index if not exists chat_messages_session_order_idx on public.chat_messages(session_id, sequence_number desc);

create table if not exists public.video_summary_cache (
    cache_key text primary key check (length(cache_key) = 64),
    video_id text not null references public.videos(video_id) on delete cascade,
    result jsonb not null check (jsonb_typeof(result) = 'object'),
    created_at timestamptz not null default now()
);

alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;
alter table public.video_summary_cache enable row level security;
revoke all on public.chat_sessions, public.chat_messages, public.video_summary_cache
    from public, anon, authenticated, service_role;
grant select on public.chat_sessions, public.chat_messages to service_role;
grant select, insert, update on public.video_summary_cache to service_role;

-- A short lease serializes requests across separate Vercel processes. A second
-- simultaneous request gets busy, rather than racing and corrupting history.
create or replace function public.tubeinsight_chat_claim(
    p_session_id uuid, p_video_id text, p_lease_seconds integer default 75
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare
    s public.chat_sessions%rowtype;
    token uuid := gen_random_uuid();
    fresh boolean := p_session_id is null;
begin
    if p_lease_seconds < 10 or p_lease_seconds > 300 then
        raise exception 'Invalid lease duration';
    end if;
    if fresh then
        insert into public.chat_sessions(video_id) values (p_video_id) returning * into s;
    else
        select * into s from public.chat_sessions where id = p_session_id for update;
        if not found or s.video_id <> p_video_id then
            return jsonb_build_object('status', 'not_found');
        end if;
    end if;
    if s.lease_token is not null and s.lease_until > clock_timestamp() then
        return jsonb_build_object('status', 'busy');
    end if;
    update public.chat_sessions set lease_token = token,
        lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds)
        where id = s.id;
    return jsonb_build_object('status', 'claimed', 'session_id', s.id,
        'token', token, 'revision', s.revision, 'fresh', fresh);
end;
$$;

-- One transaction saves BOTH messages, advances ordering, and releases the
-- lease. Token/revision checks stop an expired worker committing over a new one.
create or replace function public.tubeinsight_chat_finish(
    p_session_id uuid, p_token uuid, p_revision bigint, p_question text, p_answer text
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare s public.chat_sessions%rowtype;
begin
    select * into s from public.chat_sessions where id = p_session_id for update;
    if not found or s.lease_token is distinct from p_token or s.revision <> p_revision then
        return jsonb_build_object('status', 'conflict');
    end if;
    insert into public.chat_messages(session_id, role, content, sequence_number)
        values (s.id, 'user', p_question, s.next_sequence),
               (s.id, 'assistant', p_answer, s.next_sequence + 1);
    update public.chat_sessions set next_sequence = next_sequence + 2,
        revision = revision + 1, lease_token = null, lease_until = null,
        updated_at = clock_timestamp() where id = s.id;
    return jsonb_build_object('status', 'completed');
end;
$$;

create or replace function public.tubeinsight_chat_release(
    p_session_id uuid, p_token uuid, p_discard_new boolean default false
) returns jsonb language plpgsql security definer set search_path = '' as $$
declare s public.chat_sessions%rowtype;
begin
    select * into s from public.chat_sessions where id = p_session_id for update;
    if found and s.lease_token = p_token then
        if p_discard_new and s.revision = 0 then
            delete from public.chat_sessions where id = s.id;
        else
            update public.chat_sessions set lease_token = null, lease_until = null where id = s.id;
        end if;
    end if;
    return jsonb_build_object('status', 'released');
end;
$$;

revoke all on function public.tubeinsight_chat_claim(uuid,text,integer),
    public.tubeinsight_chat_finish(uuid,uuid,bigint,text,text),
    public.tubeinsight_chat_release(uuid,uuid,boolean) from public, anon, authenticated;
grant execute on function public.tubeinsight_chat_claim(uuid,text,integer),
    public.tubeinsight_chat_finish(uuid,uuid,bigint,text,text),
    public.tubeinsight_chat_release(uuid,uuid,boolean) to service_role;
notify pgrst, 'reload schema';
commit;
