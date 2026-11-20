"""The failure catalog (ARCHITECTURE.md section 6.1; CONTRIBUTING.md rules F1 and F6)."""

import pathlib
import re

from custom_build import failures

ROOT = pathlib.Path(__file__).resolve().parent.parent


def guide_codes():
    """Every code in the first column of the table under "Initial codes" in ARCHITECTURE.md 6.1."""
    guide = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    table = guide.split("Initial codes:", 1)[1].split("### 6.2", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    return [code for row in rows for code in re.findall(r"`([a-z_.]+)`", row.split("|")[1])]


def failure_codes():
    return {code for code, text in failures.CATALOG.items() if not text.startswith("Not a failure")}


def test_the_guide_table_is_read():
    # The failing case for the test below: an empty parse would compare nothing.
    codes = guide_codes()
    assert len(codes) > 40 and len(codes) == len(set(codes))
    assert {"db.unreachable", "write_gate.unanswered", "unhandled"} <= set(codes)


def test_the_catalog_holds_exactly_the_codes_in_the_guide():
    assert set(failures.CATALOG) == set(guide_codes())


def test_every_code_says_what_it_means():
    assert [code for code, text in failures.CATALOG.items() if not text.strip()] == []


def test_every_failure_code_has_a_severity():
    assert set(failures.SEVERITY) == failure_codes()
    assert set(failures.SEVERITY.values()) <= {"high", "medium", "low"}


def test_the_codes_the_guide_calls_not_failures_have_no_severity():
    for code in ("action.skipped", "digest.dropped", "job.succeeded", "host.heartbeat", "write_gate.would_ask"):
        assert code in failures.CATALOG and code not in failures.SEVERITY


def test_only_a_failure_code_can_be_shown_in_a_turn():
    assert isinstance(failures.SHOWN_IN_TURN, frozenset)
    assert failures.SHOWN_IN_TURN <= failure_codes()
