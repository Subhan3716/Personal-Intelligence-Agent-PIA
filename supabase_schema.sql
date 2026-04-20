-- Run this in Supabase SQL Editor to provision PIA cloud memory.

create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.user_profiles (
    id text primary key,
    email text unique not null,
    display_name text not null,
    avatar_url text default '',
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.chat_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id text not null references public.user_profiles(id) on delete cascade,
    title text not null,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.chat_messages (
    id bigserial primary key,
    chat_id uuid not null references public.chat_sessions(id) on delete cascade,
    user_id text not null references public.user_profiles(id) on delete cascade,
    role text not null check (role in ('user', 'assistant', 'system', 'tool')),
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.document_chunks (
    id uuid primary key default gen_random_uuid(),
    user_id text not null references public.user_profiles(id) on delete cascade,
    chat_id uuid references public.chat_sessions(id) on delete cascade,
    document_name text not null,
    chunk_index integer not null,
    content text not null,
    embedding vector(384) not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists idx_chat_sessions_user on public.chat_sessions(user_id, updated_at desc);
create index if not exists idx_chat_messages_chat on public.chat_messages(chat_id, created_at asc);
create index if not exists idx_document_chunks_user_chat on public.document_chunks(user_id, chat_id);

create index if not exists idx_document_chunks_embedding
on public.document_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

create or replace function public.match_document_chunks(
    query_embedding vector(384),
    match_count integer default 6,
    filter_user_id text default null,
    filter_chat_id uuid default null
)
returns table (
    id uuid,
    user_id text,
    chat_id uuid,
    document_name text,
    chunk_index integer,
    content text,
    metadata jsonb,
    similarity float,
    created_at timestamptz
)
language sql
stable
as $$
    select
        dc.id,
        dc.user_id,
        dc.chat_id,
        dc.document_name,
        dc.chunk_index,
        dc.content,
        dc.metadata,
        1 - (dc.embedding <=> query_embedding) as similarity,
        dc.created_at
    from public.document_chunks as dc
    where (filter_user_id is null or dc.user_id = filter_user_id)
      and (filter_chat_id is null or dc.chat_id = filter_chat_id)
    order by dc.embedding <=> query_embedding
    limit greatest(match_count, 1);
$$;
