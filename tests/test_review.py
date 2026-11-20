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


@pytest.mark.parametrize("line", ["- **C11.** A rule in another format.", "- **C11** No full stop.", "**C11. Not a list item.**"])
def test_a_rule_the_parser_cannot_read_is_an_error_not_a_silent_gap(line):
    with pytest.raises(ValueError, match="rule IDs in the guide"):
        review.checklist(GUIDE.replace("\n## 6. Failure rules", f"{line}\n\n## 6. Failure rules"))


def test_the_reviewer_may_only_read():
    # Read-only (W6). `--tools` sets which tools exist at all; `--allowedTools` would only pre-approve some.
    # No shell: even `git diff` takes --output=<path>, which writes a file. No MCP servers either.
    command = review.command(ITEMS)
    start = command.index("--tools")
    assert command[start + 1:start + 5] == ["Read", "Grep", "Glob", "--strict-mcp-config"]
    assert command[:2] == ["claude", "-p"] and "--json-schema" in command
    assert not {"--allowedTools", "--dangerously-skip-permissions"} & set(command)


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
    assert review.exit_code(broken, ITEMS) == 4   # 2 is argparse's code for bad arguments


def test_a_failed_rule_or_a_fix_first_verdict_exits_with_its_own_code():
    failed = report(rules={"C3": {"verdict": "fail", "evidence": "store.py:12 returns [] on a timeout"}})
    assert review.problems(failed, ITEMS) == []
    assert review.exit_code(failed, ITEMS) == 3   # 1 is left to a crash
    assert review.exit_code(report(verdict="fix_first"), ITEMS) == 3


def test_not_applicable_with_a_reason_passes():
    assert review.exit_code(report(rules={"C10": {"verdict": "not_applicable", "evidence": "no migration"}}), ITEMS) == 0


def test_the_brief_carries_the_change_the_issue_and_every_item_and_ends_with_the_rule():
    brief = review.brief("feat/x", 7, ITEMS, GUIDE, diff="+ added line", log="abc123 a commit", issue="Done looks like")
    assert "feat/x" in brief and "issue #7" in brief
    assert all(text in brief for text in ("+ added line", "abc123 a commit", "Done looks like"))
    assert all(f"- {key}: " in brief for key in ITEMS)
    rule = review.error_handling_rule(GUIDE)
    assert rule.startswith("Error handling rule: catch the specific exception") and brief.endswith(rule + "\n")
