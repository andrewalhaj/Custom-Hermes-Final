"""The throwaway database the store tests run against (issue #7), ported from the previous repository (C9).

`db` gives each test an empty database with every migration applied in order, a login that joins
`memory_agent` the way a maintainer adds a machine (OPERATIONS.md section 3), and a login that joins no
group. The tests need a Postgres 17 server named by TEST_DATABASE_URL, a superuser connection; they fail,
never skip, without it (C3). The group role is server-wide, and each test drops it when it ends, so the
server must be a throwaway one used by one test run at a time. A role left over from an interrupted run
makes the migration fail loudly instead of being dropped silently.
"""

import os
import pathlib
import uuid

import psycopg
import pytest
from psycopg import sql

MIGRATIONS = sorted((pathlib.Path(__file__).resolve().parent.parent / "migrations").glob("*.sql"))
GROUP_ROLES = ("memory_agent",)
AGENT = "host-a"   # a machine's login is named as the machine


def _drop_roles(admin, names):
    for name in names:
        admin.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(name)))


@pytest.fixture
def db():
    """Connection strings for the database's owner, an agent login and a login outside every group."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set: these tests need a Postgres 17 superuser connection")
    if not MIGRATIONS:
        pytest.fail("no migration files found under migrations/")
    name = f"t_{uuid.uuid4().hex[:12]}"
    outsider = f"{name}_outsider"
    password = uuid.uuid4().hex   # a throwaway login's password, so servers that require one (CI's) accept it
    info = psycopg.conninfo.conninfo_to_dict(url)

    def dsn(**kw):
        return psycopg.conninfo.make_conninfo(**{**info, "dbname": name, **kw})

    with psycopg.connect(url, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(dsn(), autocommit=True) as owner:
                for migration in MIGRATIONS:
                    owner.execute(migration.read_text(encoding="utf-8"))
                owner.execute(sql.SQL("create role {} login password {} in role memory_agent").format(
                    sql.Identifier(AGENT), sql.Literal(password)))
                owner.execute(sql.SQL("create role {} login password {}").format(
                    sql.Identifier(outsider), sql.Literal(password)))
            yield {"owner": dsn(), "agent": dsn(user=AGENT, password=password),
                   "outsider": dsn(user=outsider, password=password)}
        finally:
            admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))
            _drop_roles(admin, (AGENT, outsider, *GROUP_ROLES))
