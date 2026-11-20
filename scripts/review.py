"""Run the independent review before a pull request (CONTRIBUTING.md W6, issue #27).

    python scripts/review.py <branch> <issue> [--out report.json]

A separate, read-only `claude -p` at ponytail ultra reviews the branch against origin/main and must answer,
with evidence, for every rule in CONTRIBUTING.md sections 5 to 9. The checklist is read from the guide each
run, so a new rule is asked about without a change here. Exit 0: every item answered, none failed, verdict
ship. Exit 3: a rule failed or the verdict is fix_first. Exit 2: the report is not a complete review.
Anything else that goes wrong (no `claude`, no login, no structured output) crashes with a traceback and
exit 1: it is not a review.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
VERDICTS = ("pass", "fail", "not_applicable")
SECTION_ITEMS = {
    "S8": "Section 8: every guard or check the change adds or touches is proved by its own failing case (C6), "
          "and no check can pass when its tool is missing.",
    "S9": "Section 9: no instruction file is added beside the root agent guide, and a rule changed in "
          "CONTRIBUTING.md is changed in the agent guide in the same change.",
}
ULTRA = ("Ponytail level for this session: ultra. Also question the request: before accepting any part of the "
         "change, push back on any part the need does not justify. You are an independent reviewer with no "
         "prior context; do not assume the author's claims are true, check them.")
TOOLS = ["Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git ls-files:*)",
         "Bash(git status:*)", "Bash(gh issue view:*)"]   # read-only: nothing here runs a program


def checklist(guide):
    """Every C, F and L rule in sections 5 to 7 of the guide, by ID, then one item each for sections 8 and 9."""
    sections = guide[guide.index("\n## 5. "):guide.index("\n## 8. ")]
    items = dict(re.findall(r"^- \*\*([CFL]\d+)\. (.+?)\*\*", sections, re.MULTILINE))
    for letter in "CFL":
        if not any(key.startswith(letter) for key in items):
            raise ValueError(f"no {letter} rules found in CONTRIBUTING.md sections 5 to 7")
    bold_ids = re.findall(r"\*\*([CFL]\d+)", sections)   # a rule written in a form the line above cannot read
    if sorted(bold_ids) != sorted(items):
        raise ValueError(f"rule IDs in the guide {sorted(bold_ids)} are not the checklist's {sorted(items)}")
    return {**items, **SECTION_ITEMS}


def schema(items):
    answer = {"type": "object", "additionalProperties": False, "required": ["verdict", "evidence"],
              "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)},
                             "evidence": {"type": "string", "minLength": 1}}}
    return {"type": "object", "additionalProperties": False, "required": ["verdict", "findings", "rules"],
            "properties": {"verdict": {"type": "string", "enum": ["ship", "fix_first"]},
                           "findings": {"type": "string"},
                           "rules": {"type": "object", "additionalProperties": False, "required": list(items),
                                     "properties": dict.fromkeys(items, answer)}}}


def brief(branch, issue, items):
    lines = "\n".join(f"- {key}: {text}" for key, text in items.items())
    return (f"/ponytail:ponytail-review Review branch {branch} against origin/main "
            f"(git diff origin/main...{branch}). The change answers GitHub issue #{issue}; read it with "
            f"gh issue view {issue}. Read CONTRIBUTING.md sections 5 to 9 in full before you judge anything, and "
            "follow W12 (scope is the issue). Then answer for every checklist item below: pass, fail or "
            "not_applicable, each with evidence: a file and line, a command you ran with its result, or why the "
            "item does not apply to this change. Spend most of your effort on what no lint checks: C1, C3, C5, "
            "C10, F1 to F6, L4 and L5. Put your usual review findings in `findings`. Give an overall verdict: "
            f"ship or fix_first. Report only; change nothing.\n\nChecklist:\n{lines}\n")


def problems(report, items):
    """Why the report is not a complete review; empty when it is one."""
    found = []
    if report.get("verdict") not in ("ship", "fix_first"):
        found.append(f"overall verdict {report.get('verdict')!r}")
    rules = report.get("rules", {})
    for key in items:
        if key not in rules:
            found.append(f"{key}: no answer")
            continue
        if rules[key].get("verdict") not in VERDICTS:
            found.append(f"{key}: verdict {rules[key].get('verdict')!r}")
        if not str(rules[key].get("evidence", "")).strip():
            found.append(f"{key}: no evidence")
    return found


def exit_code(report, items):
    if problems(report, items):
        return 2
    failed = any(answer["verdict"] == "fail" for answer in report["rules"].values())
    return 3 if failed or report["verdict"] != "ship" else 0


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("branch")
    parser.add_argument("issue", type=int)
    parser.add_argument("--out", type=pathlib.Path, help="save the report as JSON here")
    args = parser.parse_args(argv)
    items = checklist((ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8"))
    command = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema(items)),
               "--append-system-prompt", ULTRA, "--allowedTools", *TOOLS,
               "--disallowedTools", "Edit", "Write", "NotebookEdit"]
    done = subprocess.run(command, input=brief(args.branch, args.issue, items), cwd=ROOT, check=True,
                          stdout=subprocess.PIPE, text=True)   # stderr stays on the terminal, so a failure shows why
    report = json.loads(done.stdout)["structured_output"]   # absent when claude returned no review: crash
    if args.out:
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for key in items:
        answer = report.get("rules", {}).get(key, {})
        print(f"{key:4} {answer.get('verdict', 'MISSING'):15} {answer.get('evidence', '')}")
    print(f"\n{report.get('findings', '')}\n\nVerdict: {report.get('verdict')}")
    for problem in problems(report, items):
        print(f"not a complete review: {problem}", file=sys.stderr)
    return exit_code(report, items)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
