"""Prove scripts/review.py's checklist and report check (issue #27, CONTRIBUTING.md W6).

The script's call to `claude` is not run here: it needs a login and costs a review. These tests cover what
decides the outcome: which rules the reviewer must answer for, and which reports count as a review.
"""

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("review", ROOT / "scripts" / "review.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)

GUIDE = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
ITEMS = review.checklist(GUIDE)


def report(**changes):
    """A complete passing report, with the given items or fields replaced."""
    rules = {key: {"verdict": "pass", "evidence": "tests/test_x.py:1"} for key in ITEMS}
    rules.update(changes.pop("rules", {}))
    return {"verdict": "ship", "findings": "Nothing found.", "rules": rules, **changes}


def test_the_checklist_holds_every_code_failure_and_logging_rule_in_the_guide():
    expected = [f"C{n}" for n in range(1, 11)] + [f"F{n}" for n in range(1, 7)] + [f"L{n}" for n in range(1, 6)]
    assert [key for key in ITEMS if key[0] in "CFL"] == expected
    assert ITEMS["C2"].startswith("No catch-everything blocks")


def test_the_checklist_has_one_item_each_for_sections_8_and_9_and_no_workflow_rules():
    assert {"S8", "S9"} <= set(ITEMS)
    assert not [key for key in ITEMS if key.startswith("W")]   # sections 5 to 9 only; W rules are section 4


def test_a_rule_added_to_the_guide_joins_the_checklist():
    grown = GUIDE.replace("\n## 6. Failure rules", "- **C11. A new rule.** Its text.\n\n## 6. Failure rules")
    assert review.checklist(grown)["C11"] == "A new rule."


def test_a_guide_without_its_rules_is_an_error_not_an_empty_checklist():
    with pytest.raises(ValueError, match="no L rules"):
        review.checklist(GUIDE.replace("- **L", "- **X"))


def test_the_schema_requires_an_answer_with_evidence_for_every_item():
    schema = review.schema(ITEMS)
    rules = schema["properties"]["rules"]
    assert rules["required"] == list(ITEMS) and rules["additionalProperties"] is False
    assert rules["properties"]["C3"]["required"] == ["verdict", "evidence"]
    assert rules["properties"]["C3"]["properties"]["verdict"]["enum"] == ["pass", "fail", "not_applicable"]
    assert schema["required"] == ["verdict", "findings", "rules"]


def test_a_complete_passing_report_is_a_review_and_ships():
    assert review.problems(report(), ITEMS) == []
    assert review.exit_code(report(), ITEMS) == 0


@pytest.mark.parametrize("label,bad,expect", [
    ("a missing item", lambda r: r["rules"].pop("F3"), "F3: no answer"),
    ("an unknown verdict", lambda r: r["rules"]["L5"].update(verdict="fine"), "L5: verdict 'fine'"),
    ("empty evidence", lambda r: r["rules"]["C1"].update(evidence="  "), "C1: no evidence"),
    ("no evidence key", lambda r: r["rules"]["S9"].pop("evidence"), "S9: no evidence"),
    ("no overall verdict", lambda r: r.pop("verdict"), "overall verdict None"),
    ("no rules at all", lambda r: r.pop("rules"), "C1: no answer"),
])
def test_an_incomplete_report_is_not_a_review(label, bad, expect):
    broken = report()
    bad(broken)
    assert expect in review.problems(broken, ITEMS)
    assert review.exit_code(broken, ITEMS) == 2


def test_a_failed_rule_or_a_fix_first_verdict_exits_non_zero():
    failed = report(rules={"C3": {"verdict": "fail", "evidence": "store.py:12 returns [] on a timeout"}})
    assert review.problems(failed, ITEMS) == []
    assert review.exit_code(failed, ITEMS) == 1
    assert review.exit_code(report(verdict="fix_first"), ITEMS) == 1


def test_not_applicable_with_a_reason_passes():
    assert review.exit_code(report(rules={"C10": {"verdict": "not_applicable", "evidence": "no migration"}}), ITEMS) == 0


def test_the_brief_names_the_branch_the_issue_and_every_item():
    brief = review.brief("feat/x", 7, ITEMS)
    assert "origin/main...feat/x" in brief and "gh issue view 7" in brief
    assert all(f"- {key}: " in brief for key in ITEMS)
