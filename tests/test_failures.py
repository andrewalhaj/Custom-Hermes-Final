"""The failure catalog (ARCHITECTURE.md section 6.1; CONTRIBUTING.md rules F1 and F6)."""

import pathlib
import re

from custom_build import failures

ROOT = pathlib.Path(__file__).resolve().parent.parent


def guide_rows():
    """(code, is a failure) for every code in the table under "Initial codes" in ARCHITECTURE.md 6.1."""
    guide = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    table = guide.split("Initial codes:", 1)[1].split("### 6.2", 1)[0]
    rows = [line.split("|") for line in table.splitlines() if line.startswith("| `")]
    return [(code, not row[2].strip().startswith(("Not a failure", "Not failures")))
            for row in rows for code in re.findall(r"`([a-z_.]+)`", row[1])]


def guide_codes():
    return [code for code, _ in guide_rows()]


def failure_codes():
    """The guide decides which codes are failures, so an edit to the module cannot move one out."""
    return {code for code, is_failure in guide_rows() if is_failure}


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


def test_the_guide_marks_both_kinds_of_code():
    # The failing case for the two tests around this one: a parse that called every code a failure, or none.
    kinds = dict(guide_rows())
    assert kinds["db.unreachable"] and kinds["unhandled"] and kinds["job.missed"]
    assert not kinds["host.heartbeat"] and not kinds["write_gate.denied"] and not kinds["fact_gate.passed"]


def test_the_catalog_says_not_a_failure_for_exactly_the_codes_the_guide_does():
    marked = {code for code, text in failures.CATALOG.items() if text.startswith("Not a failure")}
    assert marked == set(failures.CATALOG) - failure_codes()


def test_only_a_failure_code_can_be_shown_in_a_turn():
    assert isinstance(failures.SHOWN_IN_TURN, frozenset)
    assert failures.SHOWN_IN_TURN <= failure_codes()
