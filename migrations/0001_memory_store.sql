-- 0001: the memory schema, explicit facts, events, the store level and the agent role (issue #7).
-- ARCHITECTURE.md sections 4.2 and 4.3. Only what the first milestone uses: vectors, word search, the fact
-- lifecycle, session chunks, retention and the other roles arrive as forward migrations with their code.
-- Applied migrations are never edited; a change is a new file.

create schema memory;   -- not exposed through the Supabase Data API

create table memory.facts (
  id          uuid primary key default gen_random_uuid(),
  body        text not null,
  basis       text not null check (basis in ('user_stated', 'tool_observed', 'assistant_inferred')),
  project     text,                          -- project key (ARCHITECTURE.md section 2); null without one
  source      text not null,                 -- the machine that wrote the row
  session_id  text,
  created_at  timestamptz not null default now()
);

create table memory.events (
  id          bigint generated always as identity primary key,
  at          timestamptz not null default now(),
  source      text not null,                 -- the machine
  project     text,
  session_id  text,
  turn        integer,
  code        text not null,                 -- a code from the failure catalog, or an event name
  result      text not null check (result in ('ok', 'empty', 'failed', 'degraded')),
  reason      text,
  detail      jsonb not null default '{}'    -- IDs, scores, counts and hashes only; never content
);

-- The newest migration applied; the startup check compares it with the plugin's own number (4.3, 5.5).
-- Every later migration ends with: update memory.schema_level set level = <its own number>;
create table memory.schema_level (
  only_row boolean primary key default true check (only_row),   -- one row, ever
  level    integer not null
);
insert into memory.schema_level (level) values (1);

-- Row-level security as a backstop: a role with no policy for an action gets no rows.
alter table memory.facts enable row level security;
alter table memory.events enable row level security;
alter table memory.schema_level enable row level security;

-- Each machine's login role joins memory_agent. Logins and their passwords are created outside this
-- repository (OPERATIONS.md section 3). The role reads and inserts; it updates, deletes and alters nothing.
create role memory_agent nologin;
grant usage on schema memory to memory_agent;

grant select, insert on memory.facts to memory_agent;
create policy facts_agent_select on memory.facts for select to memory_agent using (true);
create policy facts_agent_insert on memory.facts for insert to memory_agent with check (true);

-- A machine's login is named as the machine, so it writes events only under its own name.
grant select, insert on memory.events to memory_agent;
create policy events_agent_select on memory.events for select to memory_agent using (true);
create policy events_agent_insert on memory.events for insert to memory_agent with check (source = current_user);

grant select on memory.schema_level to memory_agent;
create policy schema_level_agent_select on memory.schema_level for select to memory_agent using (true);
