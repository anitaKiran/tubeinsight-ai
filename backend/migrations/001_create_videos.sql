-- tubeInsight-ai: run once in the Supabase SQL Editor as the project owner.
begin;

create table if not exists public.videos (
    video_id text primary key
        check (char_length(video_id) = 11 and video_id ~ '^[A-Za-z0-9_-]{11}$'),
    title text null,
    url text not null,
    thumbnail_url text null,
    duration_seconds integer null check (duration_seconds >= 0),
    language text null,
    transcript jsonb not null
        check (jsonb_typeof(transcript) = 'array' and jsonb_array_length(transcript) > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.videos enable row level security;
-- No public policies. Only developer-controlled server clients use this table.
revoke all on table public.videos from public, anon, authenticated, service_role;
grant select, insert, update on table public.videos to service_role;

create or replace function public.tubeinsight_set_videos_updated_at()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
    new.created_at := old.created_at;
    new.updated_at := clock_timestamp();
    return new;
end;
$$;

revoke all on function public.tubeinsight_set_videos_updated_at()
    from public, anon, authenticated;
grant execute on function public.tubeinsight_set_videos_updated_at() to service_role;

drop trigger if exists tubeinsight_videos_updated_at on public.videos;
create trigger tubeinsight_videos_updated_at
    before update on public.videos
    for each row execute function public.tubeinsight_set_videos_updated_at();

commit;
