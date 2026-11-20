"""Prove the migrations in migrations/ (issues #7 and #25, ARCHITECTURE.md sections 4.2 and 4.3).

Each refusal is the failing case of CONTRIBUTING.md section 8's "Separate database roles" row (C6): with a
machine's role, deleting a row or altering a table is refused.
"""

import os
import re

import psycopg
import pytest
from conftest import AGENT, MIGRATIONS, refuse_existing_roles

TABLES = ("facts", "events", "schema_level")


def test_the_fixture_refuses_a_server_that_already_has_the_roles():
    # Roles are server-wide: a server that already has them is not a throwaway one, and its roles are not ours
    # to drop (C7).
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set: these tests need a Postgres 17 superuser connection")
    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute("create role memory_agent nologin")
        try:
            with pytest.raises(pytest.fail.Exception, match="memory_agent"):
                refuse_existing_roles(admin)
        finally:
            admin.execute("drop role memory_agent")


def test_row_level_security_hides_rows_the_role_has_no_policy_for(db):
    # A grant without a policy must still reach no rows, so a later migration's stray grant changes nothing.
    with psycopg.connect(db["agent"]) as conn:
        fact = add_fact(conn)
    with psycopg.connect(db["owner"]) as conn:
        conn.execute("grant delete on memory.facts to memory_agent")
    with psycopg.connect(db["agent"]) as conn:
        assert conn.execute("delete from memory.facts").rowcount == 0
    with psycopg.connect(db["agent"]) as conn:
        assert conn.execute("select count(*) from memory.facts where id = %s", (fact,)).fetchone() == (1,)


def add_fact(conn, body="The disposable store is Postgres 17.", source=AGENT):
    return conn.execute(
        "insert into memory.facts (body, basis, source) values (%s, 'user_stated', %s) returning id",
        (body, source),
    ).fetchone()[0]


def add_event(conn, source=AGENT):
    return conn.execute(
        "insert into memory.events (source, code, result) values (%s, 'db.unreachable', 'failed') returning id",
        (source,),
    ).fetchone()[0]


def test_a_new_connection_reads_a_fact_another_committed(db):
    with psycopg.connect(db["agent"]) as conn:
        fact = add_fact(conn)
    with psycopg.connect(db["agent"]) as conn:
        assert conn.execute("select body, basis, source, project from memory.facts where id = %s", (fact,)).fetchone() \
            == ("The disposable store is Postgres 17.", "user_stated", AGENT, None)


def test_the_agent_cannot_save_a_fact_under_another_name(db):
    # 0002 (#25): a fact's source is the login that wrote it, as an event's is.
    with psycopg.connect(db["agent"]) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        add_fact(conn, source="host-b")


def test_the_agent_records_an_event_under_its_own_name(db):
    with psycopg.connect(db["agent"]) as conn:
        event = add_event(conn)
        assert conn.execute("select code, result, detail from memory.events where id = %s", (event,)).fetchone() \
            == ("db.unreachable", "failed", {})


def test_the_agent_cannot_record_an_event_under_another_name(db):
    with psycopg.connect(db["agent"]) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        add_event(conn, source="host-b")


def test_a_fact_needs_one_of_the_three_bases(db):
    with psycopg.connect(db["agent"]) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("insert into memory.facts (body, basis, source) values ('x is y', 'guessed', current_user)")


def test_an_event_needs_one_of_the_four_results(db):
    with psycopg.connect(db["agent"]) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(f"insert into memory.events (source, code, result) values ('{AGENT}', 'db.query', 'error')")


@pytest.mark.parametrize("statement", [
    "delete from memory.facts",
    "update memory.facts set body = 'changed'",
    "truncate memory.facts",
    "delete from memory.events",
    "update memory.events set reason = 'changed'",
    "truncate memory.events",
    "update memory.schema_level set level = 99",
    "delete from memory.schema_level",
    "alter table memory.facts add column extra text",
    "alter table memory.events drop column detail",
    "drop table memory.facts",
    "create table memory.extra (id int)",
    "drop schema memory cascade",
])
def test_the_agent_cannot_change_or_remove_what_is_stored(db, statement):
    with psycopg.connect(db["agent"]) as conn:
        add_fact(conn)
        add_event(conn)
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


@pytest.mark.parametrize("table", TABLES)
def test_a_login_outside_memory_agent_reads_nothing(db, table):
    with psycopg.connect(db["outsider"]) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(f"select * from memory.{table}")


@pytest.mark.parametrize("table", TABLES)
def test_row_level_security_is_on(db, table):
    with psycopg.connect(db["owner"]) as conn:
        assert conn.execute("select relrowsecurity from pg_class where oid = %s::regclass",
                            (f"memory.{table}",)).fetchone() == (True,)


def test_the_group_role_cannot_log_in(db):
    with psycopg.connect(db["owner"]) as conn:
        assert conn.execute("select rolcanlogin from pg_roles where rolname = 'memory_agent'").fetchone() == (False,)


def test_the_agent_reads_the_store_level(db):
    with psycopg.connect(db["agent"]) as conn:
        assert conn.execute("select level from memory.schema_level").fetchall() == [(len(MIGRATIONS),)]


def migration_number(path):
    return int(re.match(r"(\d{4})_", path.name).group(1))


def test_migrations_are_numbered_from_one_without_gaps():
    # With test_the_agent_reads_the_store_level, this fails the newest migration when it forgets to set the level.
    assert [migration_number(p) for p in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
