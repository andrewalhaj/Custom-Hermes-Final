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


def severity_faults(severity):
    """What is wrong with a severity table, by kind; every set is empty when nothing is."""
    return {
        "missing": failure_codes() - set(severity),
        "not a failure": set(severity) - failure_codes(),
        "bad level": {code for code, level in severity.items() if level not in ("high", "medium", "low")},
    }


NO_FAULTS = {"missing": set(), "not a failure": set(), "bad level": set()}


def test_every_failure_code_has_a_severity():
    assert severity_faults(failures.SEVERITY) == NO_FAULTS


def test_a_wrong_severity_table_is_caught():
    # The failing cases for the test above.
    without = {code: level for code, level in failures.SEVERITY.items() if code != "db.unreachable"}
    assert severity_faults(without) == {**NO_FAULTS, "missing": {"db.unreachable"}}
    assert severity_faults({**failures.SEVERITY, "host.heartbeat": "low"}) == {**NO_FAULTS, "not a failure": {"host.heartbeat"}}
    assert severity_faults({**failures.SEVERITY, "db.query": "urgent"}) == {**NO_FAULTS, "bad level": {"db.query"}}


def test_the_guide_marks_both_kinds_of_code():
    # The failing case for the two tests around this one: a parse that called every code a failure, or none.
    kinds = dict(guide_rows())
    assert kinds["db.unreachable"] and kinds["unhandled"] and kinds["job.missed"]
    assert not kinds["host.heartbeat"] and not kinds["write_gate.denied"] and not kinds["fact_gate.passed"]


def test_the_catalog_says_not_a_failure_for_exactly_the_codes_the_guide_does():
    marked = {code for code, text in failures.CATALOG.items() if text.startswith("Not a failure")}
    assert marked == set(failures.CATALOG) - failure_codes()


def not_in_catalog(shown):
    return set(shown) - set(failures.CATALOG)


def test_a_code_shown_in_a_turn_is_in_the_catalog():
    assert isinstance(failures.SHOWN_IN_TURN, frozenset)
    assert not_in_catalog(failures.SHOWN_IN_TURN) == set()


def test_an_unknown_code_cannot_be_shown_in_a_turn():
    # The failing case for the test above, which an empty SHOWN_IN_TURN cannot provide.
    assert not_in_catalog({"db.unreachable", "fact_gate.withheld", "db.unreachabel"}) == {"db.unreachabel"}
