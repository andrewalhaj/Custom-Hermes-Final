"""Prove the bootstrap repository guards (CONTRIBUTING.md section 8, issue #3).

The guide links resolve, the allow-list `.gitignore` hides what must never be committed and shows what may
be, every action is pinned to a commit SHA, and Dependabot keeps those pins current.
"""

import pathlib
import re
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], check=False, capture_output=True, text=True)


# Guide links ------------------------------------------------------------------------------------------

FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def slug(heading):
    """GitHub's anchor for a heading: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower()).replace(" ", "-")


def prose(path):
    return FENCE.sub("", path.read_text(encoding="utf-8"))   # links and headings inside code blocks are examples


def guides():
    result = git("ls-files", "*.md")
    assert result.returncode == 0, result.stderr
    return [ROOT / name for name in result.stdout.split()]


def broken_links(path):
    broken = []
    for target in LINK.findall(prose(path)):
        if re.match(r"[a-z]+:", target):   # https:, mailto: and the like are not checked here
            continue
        file, _, anchor = target.partition("#")
        linked = (path.parent / file).resolve() if file else path
        if not linked.is_file():
            broken.append(f"{target}: no such file")
        elif anchor and anchor not in {slug(h) for h in HEADING.findall(prose(linked))}:
            broken.append(f"{target}: no such heading")
    return broken


def test_there_are_guides_to_check():
    assert {p.name for p in guides()} >= {"AGENTS.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "OPERATIONS.md"}


@pytest.mark.parametrize("guide", [p.name for p in guides()])
def test_every_relative_link_and_anchor_in_the_guide_resolves(guide):
    assert broken_links(ROOT / guide) == []


def test_the_link_check_finds_a_missing_file_and_a_missing_heading(tmp_path):
    page = tmp_path / "page.md"
    page.write_text("# Top\n\n[ok](#top) [file](missing.md) [anchor](#nowhere)\n\n```\n[example](gone.md)\n```\n")
    assert broken_links(page) == ["missing.md: no such file", "#nowhere: no such heading"]


@pytest.mark.parametrize("heading,anchor", [
    ("1. Hermes Agent, and where to ask about it", "1-hermes-agent-and-where-to-ask-about-it"),
    ("8.1 Repository settings", "81-repository-settings"),
    ("Lexical recall baseline", "lexical-recall-baseline"),
])
def test_slug_matches_github_anchors(heading, anchor):
    assert slug(heading) == anchor


# The allow-list .gitignore ----------------------------------------------------------------------------
# `git check-ignore` answers for a path that need not exist: 0 when it is ignored, 1 when not, 128 on error.

HIDDEN = [
    ".env",
    "secrets.json",
    "notes.md",
    "key.pem",
    ".serena/project.yml",
    ".venv/bin/python",
    ".pytest_cache/README.md",
    ".ruff_cache/CACHEDIR.TAG",
    "tests/.env",
    "tests/key.pem",
    "tests/__pycache__/test_bootstrap.cpython-314.pyc",
    ".github/.env",
    ".github/workflows/token.txt",
    ".githooks/.env",
    ".githooks/notes.md",
    "migrations/.env",
    "migrations/notes.md",
]
VISIBLE = [
    ".gitignore",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "OPERATIONS.md",
    "pyproject.toml",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/new.yml",
    ".githooks/pre-commit",
    "tests/test_new.py",
    "migrations/0001_memory_store.sql",
    "migrations/0002_next.sql",
]


@pytest.mark.parametrize("path", HIDDEN)
def test_credential_and_runtime_files_are_ignored(path):
    result = git("check-ignore", "-q", "--no-index", path)
    assert result.returncode == 0, f"{path} would show as untracked: check-ignore exited {result.returncode} {result.stderr}"


@pytest.mark.parametrize("path", VISIBLE)
def test_accepted_paths_stay_visible(path):
    result = git("check-ignore", "-q", "--no-index", path)
    assert result.returncode == 1, f"{path} would be hidden: check-ignore exited {result.returncode} {result.stderr}"


def test_no_tracked_file_is_ignored():
    result = git("ls-files", "-ci", "--exclude-standard")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "", f"tracked files the .gitignore hides:\n{result.stdout}"


# Action pins and Dependabot -------------------------------------------------------------------------

def unpinned_actions(directory):
    """Each `uses:` in the directory's workflow files, on a step or a whole job, that is not a full commit SHA."""
    found = []
    for path in sorted(directory.glob("*.yml")):
        for job in yaml.safe_load(path.read_text())["jobs"].values():
            for used in [job.get("uses"), *(step.get("uses") for step in job.get("steps", []))]:
                if used and not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", used):
                    found.append(f"{path.name}: {used}")
    return found


def test_every_action_is_pinned_to_a_full_commit_sha():
    steps = yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"]["tests"]["steps"]
    assert any("uses" in step for step in steps)   # there is something to check
    assert unpinned_actions(WORKFLOWS) == []


def test_the_pin_check_reads_every_workflow_file(tmp_path):
    (tmp_path / "ci.yml").write_text("jobs:\n  a:\n    steps:\n      - uses: actions/checkout@" + "3" * 40 + "\n")
    (tmp_path / "release.yml").write_text(
        "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@v7\n"
        "  c:\n    uses: owner/repo/.github/workflows/shared.yml@main\n")
    assert unpinned_actions(tmp_path) == [
        "release.yml: actions/checkout@v7", "release.yml: owner/repo/.github/workflows/shared.yml@main"]


def test_dependabot_keeps_the_pinned_actions_current():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    assert config["version"] == 2
    actions = next(u for u in config["updates"] if u["package-ecosystem"] == "github-actions")
    assert actions["directory"] == "/"
    assert actions["schedule"]["interval"] == "weekly"
    assert actions["commit-message"]["prefix"] == "ci"   # its title becomes a conventional commit on main (4.8)
