-- HackMate Community — Supabase schema
-- Run this once in the Supabase SQL editor for a fresh project.

create extension if not exists "pgcrypto";

-- ── profiles ──────────────────────────────────────────
-- One row per GitHub-authenticated user, populated automatically on signup.
create table profiles (
  id uuid primary key references auth.users on delete cascade,
  github_username text not null,
  avatar_url text,
  created_at timestamptz not null default now()
);

create function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, github_username, avatar_url)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'user_name', new.raw_user_meta_data->>'preferred_username', 'user'),
    new.raw_user_meta_data->>'avatar_url'
  );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ── categories (subforums) ───────────────────────────
create table categories (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name text not null,
  description text not null default '',
  sort_order int not null default 0
);

insert into categories (slug, name, description, sort_order) values
  ('general', 'General', 'Anything HackMate related that doesn''t fit elsewhere', 0),
  ('help', 'Help', 'Stuck on a build? Ask here', 1),
  ('bugs', 'Bugs', 'Report issues with HackMate', 2),
  ('showcase', 'Showcase', 'Show off your successful hackintosh build', 3);

-- ── posts ─────────────────────────────────────────────
create table posts (
  id uuid primary key default gen_random_uuid(),
  category_id uuid not null references categories on delete cascade,
  author_id uuid not null references profiles on delete cascade,
  title text not null check (char_length(title) between 1 and 300),
  body text not null default '',
  created_at timestamptz not null default now()
);

create index posts_category_idx on posts (category_id, created_at desc);

-- ── comments ──────────────────────────────────────────
create table comments (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references posts on delete cascade,
  author_id uuid not null references profiles on delete cascade,
  parent_id uuid references comments on delete cascade,
  body text not null check (char_length(body) between 1 and 5000),
  created_at timestamptz not null default now()
);

create index comments_post_idx on comments (post_id, created_at);

-- ── votes ─────────────────────────────────────────────
-- One vote per user per target (post or comment); value is always +1 (simple upvote, no downvotes).
create table votes (
  user_id uuid not null references profiles on delete cascade,
  post_id uuid references posts on delete cascade,
  comment_id uuid references comments on delete cascade,
  created_at timestamptz not null default now(),
  constraint votes_one_target check (
    (post_id is not null and comment_id is null) or
    (post_id is null and comment_id is not null)
  ),
  unique (user_id, post_id),
  unique (user_id, comment_id)
);

create index votes_post_idx on votes (post_id);
create index votes_comment_idx on votes (comment_id);

-- ── vote count views ──────────────────────────────────
create view post_scores as
  select post_id, count(*)::int as score
  from votes
  where post_id is not null
  group by post_id;

create view comment_scores as
  select comment_id, count(*)::int as score
  from votes
  where comment_id is not null
  group by comment_id;

-- ── row level security ────────────────────────────────
alter table profiles enable row level security;
alter table categories enable row level security;
alter table posts enable row level security;
alter table comments enable row level security;
alter table votes enable row level security;

create policy "profiles are publicly readable" on profiles for select using (true);

create policy "categories are publicly readable" on categories for select using (true);

create policy "posts are publicly readable" on posts for select using (true);
create policy "logged-in users can create posts" on posts for insert with check (auth.uid() = author_id);
create policy "authors can edit their own posts" on posts for update using (auth.uid() = author_id);
create policy "authors can delete their own posts" on posts for delete using (auth.uid() = author_id);

create policy "comments are publicly readable" on comments for select using (true);
create policy "logged-in users can create comments" on comments for insert with check (auth.uid() = author_id);
create policy "authors can edit their own comments" on comments for update using (auth.uid() = author_id);
create policy "authors can delete their own comments" on comments for delete using (auth.uid() = author_id);

create policy "votes are publicly readable" on votes for select using (true);
create policy "logged-in users can vote" on votes for insert with check (auth.uid() = user_id);
create policy "users can remove their own vote" on votes for delete using (auth.uid() = user_id);
