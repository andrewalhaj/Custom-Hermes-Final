"""Prove each guard step in .github/workflows/ci.yml against its failing and passing cases (CONTRIBUTING.md C6).

Ported from the previous repository under rule C9 (issue #3). Each test takes a step's `run` script from the
workflow and runs it the way GitHub runs `shell: bash` (`bash --noprofile --norc -eo pipefail`) inside a
throwaway git repository built for the case. A failing case passes only if the step fails with the message
that names its cause, so a step that breaks for some other reason cannot pass a test by accident.
Needs `git`, `ruff`, `gitleaks` and `python` on PATH, as the CI job has them.
"""

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

NOQA = "no" + "qa"  # kept apart so the noqa ban does not match this file
# The repository's own configuration. It ends inside [tool.ruff.lint], so a case can append keys to that table.
CONFIG = (ROOT / "pyproject.toml").read_text()
CODE = "x = 1\n"


def steps():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["tests"]["steps"]


def step_script(name):
    matches = [s for s in steps() if s.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r} in {WORKFLOW}"
    assert matches[0].get("shell") == "bash", f"step {name!r} must set shell: bash, so pipefail applies"
    return matches[0]["run"]


def run_in_repo(tmp_path, script, files):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        subprocess.run(["git", "-C", str(tmp_path), "add", "-f", name], check=True)
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                            check=False, cwd=tmp_path, capture_output=True, text=True)  # the exit code is the result
    return result.returncode, result.stdout + result.stderr


def check(tmp_path, script, files, expect):
    """expect is None for a case that must pass, or the message a failing case must print."""
    rc, output = run_in_repo(tmp_path, script, files)
    if expect is None:
        assert rc == 0, output
    else:
        assert rc != 0, output
        assert expect in output, output


def test_workflow_runs_on_pull_requests_and_main():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow[True] if True in workflow else workflow["on"]  # YAML 1.1 reads a bare `on` key as True
    assert triggers["pull_request"]["branches"] == ["main"]
    assert triggers["push"]["branches"] == ["main"]
    assert list(workflow["jobs"]) == ["tests", "review"]   # `tests` is the status check to require (8.2)
    commands = [s.get("run", "") for s in steps()]
    assert "ruff check ." in commands
    assert "python -m pytest -q" in commands
    python = next(s for s in steps() if s.get("uses", "").startswith("actions/setup-python"))
    assert python["with"]["python-version"] == "3.14"


def test_the_dev_tools_are_installed_from_the_pinned_group_before_they_run():
    commands = [s.get("run", "") for s in steps()]
    install = "pip install --group dev"   # ruff, pytest and PyYAML, pinned once in pyproject.toml (8.2)
    assert install in commands
    assert commands.index(install) < commands.index("ruff check .") < commands.index("python -m pytest -q")


NOQA_STEP = "no noqa that can silence a protected rule"
NOQA_CASES = [
    ("clean", {"a.py": CODE}, None),
    ("another rule only", {"a.py": f"import os  # {NOQA}: F401\n"}, None),
    ("names BLE001", {"a.py": f"x = 1  # {NOQA}: BLE001\n"}, "git grep exited 0"),
    ("names S110 in another case", {"a.py": f"x = 1  # {NOQA.upper()}: s110\n"}, "git grep exited 0"),
    ("lists E722 after another rule", {"a.py": f"x = 1  # {NOQA}: F401, E722\n"}, "git grep exited 0"),
    ("bare", {"a.py": f"x = 1  # {NOQA}\n"}, "git grep exited 0"),
    ("bare, no space, trailing text", {"a.py": f"x = 1  #{NOQA}  because\n"}, "git grep exited 0"),
    ("file-level ruff", {"a.py": f"# ruff: {NOQA}\nx = 1\n"}, "git grep exited 0"),
    ("file-level flake8", {"a.py": f"# flake8: {NOQA}\nx = 1\n"}, "git grep exited 0"),
    ("names S112", {"a.py": f"x = 1  # {NOQA}: S112\n"}, "git grep exited 0"),
    ("names a G code", {"a.py": f"x = 1  # {NOQA}: G004\n"}, "git grep exited 0"),
    ("names a LOG code, no space", {"a.py": f"x = 1  # {NOQA}:LOG015\n"}, "git grep exited 0"),
    ("names TID251 after another rule", {"a.py": f"x = 1  # {NOQA}: F401,TID251\n"}, "git grep exited 0"),
    ("another rule that only ends like a code", {"a.py": f"x = 1  # {NOQA}: PLC0415, RUF100\n"}, None),
]


@pytest.mark.parametrize("label,files,expect", NOQA_CASES, ids=[c[0] for c in NOQA_CASES])
def test_noqa_ban(tmp_path, label, files, expect):
    check(tmp_path, step_script(NOQA_STEP), files, expect)


def test_noqa_ban_fails_when_git_fails(tmp_path):
    script = step_script(NOQA_STEP).replace("git grep -n", "git --not-a-real-option grep -n")
    check(tmp_path, script, {"a.py": CODE}, "git grep exited 129")


# ruff honours more suppression forms than the pattern above knows, so a second step asks ruff itself:
# with every suppression comment ignored, none of the protected rules may fire anywhere.
UNSUPPRESSED_STEP = "no protected rule fires once every suppression comment is ignored"
BROAD = {"BLE001": "try:\n    x = 1\nexcept Exception:{line}\n    x = 2\n",
         "S110": "try:\n    x = 1\nexcept Exception:{line}\n    pass{line}\n",
         "E722": "try:\n    x = 1\nexcept:{line}\n    x = 2\n",
         # the rules #16 added (C2, L1); a comment must not silence them either (#19)
         "S112": "for i in ():\n    try:\n        x = 1\n    except Exception:{line}\n        continue{line}\n",
         "G004": "import logging\n\nlogging.getLogger(__name__).warning(f\"{{__name__}}\"){line}\n",
         "LOG015": "import logging\n\nlogging.info(\"x\"){line}\n",
         "TID251": "import contextlib\n\nwith contextlib.suppress(ValueError):{line}\n    x = 1\n"}
LINE_FORMS = [f"# {NOQA} : {{rule}}", "# ruff: ignore[{rule}]"]
FILE_FORMS = ["# ruff: disable[{rule}]", "# ruff: file-ignore[{rule}]", f"# ruff : {NOQA}", f"# flake8 : {NOQA}"]
UNSUPPRESSED_CASES = [("clean", {"pyproject.toml": CONFIG, "a.py": CODE}, None),
                      ("another rule suppressed", {"pyproject.toml": CONFIG, "a.py": f"import os  # {NOQA}: F401\n"}, None)]
UNSUPPRESSED_CASES += [
    ("a nested file", {"pyproject.toml": CONFIG, "a.py": CODE,
                       "pkg/sub/b.py": "# ruff: file-ignore[BLE001]\n" + BROAD["BLE001"].format(line="")}, ": BLE001 "),
    ("ruff cannot read its configuration", {"pyproject.toml": "[tool.ruff.lint]\nselect = 1\n", "a.py": CODE},
     "ruff exited 2"),
    # The ban is on the use, not only the import: inside Hermes `logging.config` is already loaded (#17).
    ("logging.config used through a plain import",
     {"pyproject.toml": CONFIG, "a.py": "import logging\n\nlogging.config.dictConfig({})\n"}, ": TID251 "),
]
for rule, body in BROAD.items():
    UNSUPPRESSED_CASES += [(f"{rule} under {form}", {"pyproject.toml": CONFIG, "a.py": body.format(
        line="  " + form.format(rule=rule))}, f": {rule} ") for form in LINE_FORMS]
    UNSUPPRESSED_CASES += [(f"{rule} under {form}", {"pyproject.toml": CONFIG, "a.py": form.format(rule=rule) + "\n"
                            + body.format(line="")}, f": {rule} ") for form in FILE_FORMS]


@pytest.mark.parametrize("label,files,expect", UNSUPPRESSED_CASES, ids=[c[0] for c in UNSUPPRESSED_CASES])
def test_no_broad_catch_survives_under_a_suppression_comment(tmp_path, label, files, expect):
    check(tmp_path, step_script(UNSUPPRESSED_STEP), files, expect)


def test_the_unsuppressed_lint_fails_when_ruff_is_missing(tmp_path):
    script = step_script(UNSUPPRESSED_STEP).replace("ruff check", "/nonexistent/ruff check")
    check(tmp_path, script, {"pyproject.toml": CONFIG, "a.py": CODE}, "ruff exited 127")


PROBE_STEP = "the error-handling rules are switched on"
PROBE_CASES = [
    ("configured", {"pyproject.toml": CONFIG}, None),
    ("ignore BLE001", {"pyproject.toml": CONFIG + 'ignore = ["BLE001"]\n'}, "ruff no longer reports BLE001"),
    ("extend-ignore prefix E", {"pyproject.toml": CONFIG + 'extend-ignore = ["E"]\n'}, "ruff no longer reports E722"),
    ("select replaces defaults", {"pyproject.toml": '[tool.ruff.lint]\nselect = ["F"]\n'}, "ruff exited 0"),
    ("top-level ignore E722", {"pyproject.toml": '[tool.ruff]\nignore = ["E722"]\n' + CONFIG},
     "ruff no longer reports E722"),
    ("root ruff.toml ignores S110",
     {"pyproject.toml": CONFIG, "ruff.toml": '[lint]\nextend-select = ["BLE001", "S110"]\nignore = ["S110"]\n'},
     "ruff no longer reports S110"),
    ("ignore S112", {"pyproject.toml": CONFIG + 'ignore = ["S112"]\n'}, "ruff no longer reports S112"),
    ("ignore G004", {"pyproject.toml": CONFIG + 'ignore = ["G004"]\n'}, "ruff no longer reports G004"),
    ("ignore prefix LOG", {"pyproject.toml": CONFIG + 'extend-ignore = ["LOG"]\n'}, "ruff no longer reports LOG002"),
    ("ignore G001", {"pyproject.toml": CONFIG + 'ignore = ["G001"]\n'}, "ruff no longer reports G001"),
    ("ignore G003", {"pyproject.toml": CONFIG + 'ignore = ["G003"]\n'}, "ruff no longer reports G003"),
    ("ignore LOG002", {"pyproject.toml": CONFIG + 'ignore = ["LOG002"]\n'}, "ruff no longer reports LOG002"),
    ("ignore LOG015", {"pyproject.toml": CONFIG + 'ignore = ["LOG015"]\n'}, "ruff no longer reports LOG015"),
    ("suppress no longer banned",
     {"pyproject.toml": CONFIG.replace('"contextlib.suppress".msg', '"contextlib.nullcontext".msg')},
     "ruff no longer bans contextlib.suppress"),
    ("basicConfig no longer banned", {"pyproject.toml": CONFIG.replace('"logging.basicConfig"', '"logging.shutdown"')},
     "ruff no longer bans logging.basicConfig"),
    ("logging.config no longer banned", {"pyproject.toml": CONFIG.replace('"logging.config"', '"logging.handlers"')},
     "ruff no longer bans logging.config"),
]


@pytest.mark.parametrize("label,files,expect", PROBE_CASES, ids=[c[0] for c in PROBE_CASES])
def test_probe(tmp_path, label, files, expect):
    check(tmp_path, step_script(PROBE_STEP), files, expect)


def test_probe_fails_when_ruff_is_missing(tmp_path):
    script = step_script(PROBE_STEP)
    assert script.count("out=$(ruff check") == 1
    check(tmp_path, script.replace("out=$(ruff check", "out=$(/nonexistent/ruff check"), {"pyproject.toml": CONFIG},
          "ruff exited 127")


COVERAGE_STEP = "ruff lints every tracked Python file"
COVERAGE_CASES = [
    ("every file, nested and tests", {"pyproject.toml": CONFIG, "a.py": CODE, "pkg/b.py": CODE,
                                      "tests/test_c.py": CODE}, None),
    ("include narrows to src", {"pyproject.toml": '[tool.ruff]\ninclude = ["src/**/*.py"]\n' + CONFIG,
                                "a.py": CODE, "src/b.py": CODE}, "does not lint:\na.py"),
    ("default exclude dist", {"pyproject.toml": CONFIG, "dist/y.py": CODE}, "does not lint:\ndist/y.py"),
    ("gitignore matches a tracked file", {"pyproject.toml": CONFIG, ".gitignore": "ignored.py\n",
                                          "a.py": CODE, "ignored.py": CODE}, "does not lint:\nignored.py"),
    ("extend-exclude", {"pyproject.toml": '[tool.ruff]\nextend-exclude = ["pkg/"]\n' + CONFIG,
                        "a.py": CODE, "pkg/b.py": CODE}, "does not lint:\npkg/b.py"),
]


@pytest.mark.parametrize("label,files,expect", COVERAGE_CASES, ids=[c[0] for c in COVERAGE_CASES])
def test_coverage(tmp_path, label, files, expect):
    check(tmp_path, step_script(COVERAGE_STEP), files, expect)


@pytest.mark.parametrize("tool,old", [("ruff", 'run("ruff",'), ("git", 'run("git",')])
def test_coverage_fails_when_a_tool_is_missing(tmp_path, tool, old):
    script = step_script(COVERAGE_STEP).replace(old, f'run("/nonexistent/{tool}",')
    check(tmp_path, script, {"pyproject.toml": CONFIG, "a.py": CODE}, f"/nonexistent/{tool}")


CONFIG_STEP = "ruff configuration lives in the root pyproject.toml and narrows nothing"
OUTSIDE = "ruff configuration outside the root pyproject.toml: "
CONFIG_CASES = [
    ("root pyproject only", {"pyproject.toml": CONFIG, "a.py": CODE}, None),
    ("per-file ignore for another rule",
     {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["F401"]\n'}, None),
    ("nested ruff.toml", {"pyproject.toml": CONFIG, "pkg/ruff.toml": '[lint]\nignore = ["BLE001"]\n'},
     OUTSIDE + "pkg/ruff.toml"),
    ("nested .ruff.toml", {"pyproject.toml": CONFIG, "pkg/.ruff.toml": '[lint]\nignore = ["BLE001"]\n'},
     OUTSIDE + "pkg/.ruff.toml"),
    ("nested pyproject.toml", {"pyproject.toml": CONFIG, "pkg/pyproject.toml": '[tool.ruff.lint]\nignore = ["E722"]\n'},
     OUTSIDE + "pkg/pyproject.toml"),
    ("root ruff.toml", {"pyproject.toml": CONFIG, "ruff.toml": "line-length = 100\n"}, OUTSIDE + "ruff.toml"),
    ("tool.ruff extend-exclude", {"pyproject.toml": '[tool.ruff]\nextend-exclude = ["pkg/"]\n' + CONFIG},
     "extend-exclude: pkg/"),
    ("tool.ruff.lint exclude", {"pyproject.toml": CONFIG + 'exclude = ["x.py"]\n'}, "exclude: x.py"),
    ("per-file ignore S110", {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["S110"]\n'},
     "per-file-ignores: tests/*: S110"),
    ("per-file ignore ALL", {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"tests/*" = ["ALL"]\n'},
     "per-file-ignores: tests/*: ALL"),
    ("extend-per-file ignore prefix E",
     {"pyproject.toml": CONFIG + '[tool.ruff.lint.extend-per-file-ignores]\n"x.py" = ["E"]\n'},
     "extend-per-file-ignores: x.py: E"),
    ("no pyproject.toml", {"a.py": CODE}, "no pyproject.toml at the repository root"),
    ("ignore a LOG code the probe does not test", {"pyproject.toml": CONFIG + 'ignore = ["LOG001"]\n'}, "ignore: LOG001"),
    ("extend-ignore a G code the probe does not test", {"pyproject.toml": CONFIG + 'extend-ignore = ["G010"]\n'},
     "extend-ignore: G010"),
    ("ignore another rule", {"pyproject.toml": CONFIG + 'ignore = ["F401"]\n'}, None),
    ("extend loads another settings file", {"pyproject.toml": '[tool.ruff]\nextend = "base.toml"\n' + CONFIG},
     "extend: base.toml"),
    ("select narrows the rules", {"pyproject.toml": CONFIG + 'select = ["E", "G004"]\n'}, "select: E"),
    ("top-level select", {"pyproject.toml": '[tool.ruff]\nselect = ["G004"]\n' + CONFIG}, "select: G004"),
    ("per-file ignore G", {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"pkg/*" = ["G"]\n'},
     "per-file-ignores: pkg/*: G"),
    ("per-file ignore LOG015", {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"pkg/*" = ["LOG015"]\n'},
     "per-file-ignores: pkg/*: LOG015"),
    ("per-file ignore TID251 and S112",
     {"pyproject.toml": CONFIG + '[tool.ruff.lint.per-file-ignores]\n"pkg/*" = ["TID251", "S112"]\n'},
     "per-file-ignores: pkg/*: TID251"),
]


@pytest.mark.parametrize("label,files,expect", CONFIG_CASES, ids=[c[0] for c in CONFIG_CASES])
def test_config_location(tmp_path, label, files, expect):
    check(tmp_path, step_script(CONFIG_STEP), files, expect)


# BLE001 skips a broad handler that re-raises or logs the exception; C2 bans those too outside the two wrappers
# (CONTRIBUTING.md 5.4). L1 bans adding log handlers, which no ruff rule sees.
HANDLER_STEP = "no broad handler outside the two wrappers, and no added log handlers"
BROAD_FORMS = {
    "re-raises": "def f():\n    try:\n        x = 1\n    except Exception:\n        raise\n",
    "logs the exception": "def f(log):\n    try:\n        x = 1\n    except BaseException:\n        log.exception('x')\n",
    "bare": "def f():\n    try:\n        x = 1\n    except:\n        raise\n",
    "in a tuple": "def f():\n    try:\n        x = 1\n    except (ValueError, Exception):\n        raise\n",
    "except star": "def f():\n    try:\n        x = 1\n    except* Exception:\n        raise\n",
    "by module path": "import builtins\ndef f():\n    try:\n        x = 1\n    except builtins.Exception:\n        raise\n",
    "at module level": "try:\n    x = 1\nexcept Exception:\n    raise\n",
}
HANDLER_CASES = [
    ("clean", {"a.py": CODE}, None),
    ("a named exception", {"a.py": "def f():\n    try:\n        x = 1\n    except ValueError:\n        raise\n"}, None),
    ("a name that only contains Exception",
     {"a.py": "def f():\n    try:\n        x = 1\n    except ExceptionGroup:\n        raise\n"}, None),
]
HANDLER_CASES += [(f"broad, {label}", {"pkg/a.py": body}, "broad handler outside the wrappers: pkg/a.py:")
                  for label, body in BROAD_FORMS.items()]
HANDLER_CASES += [
    ("addHandler", {"a.py": "import logging\nlogging.getLogger(__name__).addHandler(logging.NullHandler())\n"},
     "log handler added: a.py:2"),
    ("not Python", {"a.py": "def f(:\n"}, "SyntaxError"),
    # A handler put straight into a logger's list, without addHandler (#17).
    ("handlers.append", {"a.py": "import logging\nlogging.root.handlers.append(logging.NullHandler())\n"},
     "log handler added: a.py:2"),
    ("handlers.extend", {"a.py": "def f(log, h):\n    log.handlers.extend([h])\n"}, "log handler added: a.py:2"),
    ("handlers.insert", {"a.py": "def f(log, h):\n    log.handlers.insert(0, h)\n"}, "log handler added: a.py:2"),
    ("handlers assigned", {"a.py": "def f(log, h):\n    log.handlers = [h]\n"}, "log handler added: a.py:2"),
    ("handlers added to in place", {"a.py": "def f(log, h):\n    log.handlers += [h]\n"}, "log handler added: a.py:2"),
    ("handlers assigned with an annotation", {"a.py": "def f(log, h):\n    log.handlers: list = [h]\n"},
     "log handler added: a.py:2"),
    ("handlers only read", {"a.py": "def f(log):\n    return len(log.handlers), list(log.handlers)\n"}, None),
    ("another list appended to", {"a.py": "def f(items, x):\n    items.append(x)\n    items.rows.append(x)\n"}, None),
    ("a file name with a space", {"my mod.py": BROAD_FORMS["re-raises"]},
     "broad handler outside the wrappers: my mod.py:4 in f"),
]


# A broad handler written through another name is still broad (#18). The check follows assignments and
# imports anywhere in the file, whatever their scope, so it errs toward refusing.
HANDLER = "def f():\n    try:\n        x = 1\n    except {name}:\n        raise\n"
ALIAS_FORMS = {
    "an assignment": "E = Exception\n" + HANDLER.format(name="E"),
    "a chain of assignments": "A = BaseException\nB = A\n" + HANDLER.format(name="B"),
    "a chain written backwards": "def g():\n    return B\nB = A\nA = Exception\n" + HANDLER.format(name="B"),
    "a tuple held in a name": "ERRORS = (ValueError, Exception)\n" + HANDLER.format(name="ERRORS"),
    "an alias inside a tuple": "E = Exception\n" + HANDLER.format(name="(ValueError, E)"),
    "an annotated assignment": "E: type = Exception\n" + HANDLER.format(name="E"),
    "an import under another name": "from builtins import Exception as E\n" + HANDLER.format(name="E"),
    "an assignment inside the function": "def f():\n    E = Exception\n    try:\n        x = 1\n    except E:\n        raise\n",
    "a walrus": "if (E := Exception):\n    pass\n" + HANDLER.format(name="E"),
    "a chain through an import": "E = Exception\nfrom m import E as F\n" + HANDLER.format(name="F"),   # by name: m.E need not be this E (#37)
}
HANDLER_CASES += [(f"alias, {label}", {"pkg/a.py": body}, "broad handler outside the wrappers: pkg/a.py:")
                  for label, body in ALIAS_FORMS.items()]
HANDLER_CASES += [
    ("a name for a named exception", {"a.py": "E = ValueError\n" + HANDLER.format(name="E")}, None),
    ("a name for a tuple of named exceptions", {"a.py": "E = (ValueError, KeyError)\n" + HANDLER.format(name="E")}, None),
    ("a subclass of Exception", {"a.py": "class Mine(Exception):\n    pass\n" + HANDLER.format(name="Mine")}, None),
    ("an alias never used in a handler", {"a.py": "E = Exception\nraise E('x')\n"}, None),
    ("an annotation with no value", {"a.py": "E: type\n" + HANDLER.format(name="E")}, None),
    # A target that is not a plain name must not crash the check (#37). The handler here is narrow, so this
    # does not show whether such a target is followed; it is not (CONTRIBUTING.md 5.4).
    ("an attribute given Exception", {"a.py": "class C:\n    def m(self):\n        self.E = Exception\n"
                                      + HANDLER.format(name="ValueError")}, None),
    ("a plain import, then a handler that is not a name",
     {"a.py": "from builtins import Exception\nERRS = (ValueError,)\n" + HANDLER.format(name="ERRS[0]")}, None),
]


@pytest.mark.parametrize("label,files,expect", HANDLER_CASES, ids=[c[0] for c in HANDLER_CASES])
def test_handler_check(tmp_path, label, files, expect):
    check(tmp_path, step_script(HANDLER_STEP), files, expect)


def test_the_allow_list_admits_only_a_named_wrapper_by_its_qualified_name(tmp_path):
    # The boundary wrapper wraps each function Hermes calls (ARCHITECTURE.md section 2), so it is a decorator
    # whose inner function holds the handler; a method of the same name in a class is not the wrapper.
    script = step_script(HANDLER_STEP)
    assert "ALLOWED = set()" in script   # empty until the failure module's two wrappers exist (C2)
    script = script.replace("ALLOWED = set()", 'ALLOWED = {"pkg/failures.py:boundary.wrapped"}')
    decorator = ("def boundary(fn):\n    def wrapped(*a):\n        try:\n            return fn(*a)\n"
                 "        except BaseException:\n            raise\n    return wrapped\n")
    check(tmp_path, script, {"pkg/failures.py": decorator}, None)
    method = "class Other:\n    def boundary(self):\n        try:\n            x = 1\n        except Exception:\n            raise\n"
    check(tmp_path / "method", script, {"pkg/failures.py": decorator + method},
          "broad handler outside the wrappers: pkg/failures.py:12 in Other.boundary")
    check(tmp_path / "elsewhere", script, {"pkg/other.py": decorator},   # the same name in another file is not it
          "broad handler outside the wrappers: pkg/other.py:5 in boundary.wrapped")


def test_the_handler_check_fails_when_git_is_missing(tmp_path):
    script = step_script(HANDLER_STEP).replace('["git", "ls-files"', '["/nonexistent/git", "ls-files"')
    check(tmp_path, script, {"a.py": CODE}, "/nonexistent/git")


def test_config_location_fails_when_git_is_missing(tmp_path):
    script = step_script(CONFIG_STEP).replace('["git", "ls-files"', '["/nonexistent/git", "ls-files"')
    check(tmp_path, script, {"pyproject.toml": CONFIG}, "/nonexistent/git")


# The secret scan (CONTRIBUTING.md section 8, W13): gitleaks in CI over the whole history, and as a
# pre-commit hook over what is staged.

GITLEAKS_VERSION = "8.30.1"
HOOK = WORKFLOW.parent.parent.parent / ".githooks" / "pre-commit"
SCAN_STEP = "no secret in the repository's history"
TOKEN_FILE = "leaky.py"   # the redacted findings must name it


def fake_token():
    # A GitHub token's shape, put together at run time so no key-shaped literal sits in the repository.
    return "gh" + "p_" + "R8vXq2LmT5wZ9kPa3Nc7Jd1Hf6Gs4Bt0Yu2E"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   check=True, capture_output=True)


def committed_repo(tmp_path, files):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, body in files.items():
        (tmp_path / name).write_text(body)
        git(tmp_path, "add", "-f", name)
    git(tmp_path, "commit", "-q", "-m", "x")


def merge_brings_in_a_token(tmp_path):
    # The merge commit adds a file neither parent has; plain `git log -p` shows merges without a diff.
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    for branch, name in (("main", "a.py"), ("side", "b.py"), ("main", "c.py")):
        if branch == "side":
            git(tmp_path, "switch", "-q", "-c", "side")
        elif name == "c.py":
            git(tmp_path, "switch", "-q", "main")
        (tmp_path / name).write_text(CODE)
        git(tmp_path, "add", name)
        git(tmp_path, "commit", "-q", "-m", name)
    git(tmp_path, "merge", "-q", "--no-commit", "--no-ff", "side")
    (tmp_path / TOKEN_FILE).write_text(f'token = "{fake_token()}"\n')
    git(tmp_path, "add", TOKEN_FILE)
    git(tmp_path, "commit", "-q", "-m", "merge")


def run_scan(cwd, path=None):
    env = None if path is None else {"PATH": path, "HOME": str(cwd)}
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step_script(SCAN_STEP)],
                            check=False, cwd=cwd, capture_output=True, text=True, env=env)
    return result.returncode, result.stdout + result.stderr


def test_the_scan_passes_a_clean_history(tmp_path):
    committed_repo(tmp_path, {"a.py": CODE})
    code, output = run_scan(tmp_path)
    assert code == 0, output


def test_the_scan_refuses_a_committed_token_and_names_its_file_redacted(tmp_path):
    committed_repo(tmp_path, {TOKEN_FILE: f'token = "{fake_token()}"\n'})
    code, output = run_scan(tmp_path)
    assert code != 0 and "gitleaks found a secret" in output, output
    assert TOKEN_FILE in output and fake_token() not in output


def test_the_scan_refuses_a_token_a_merge_commit_brings_in(tmp_path):
    merge_brings_in_a_token(tmp_path)
    code, output = run_scan(tmp_path)
    assert code != 0 and TOKEN_FILE in output, output
    assert fake_token() not in output


def test_the_scan_fails_when_git_cannot_read_the_history(tmp_path):
    # gitleaks itself exits 0 when git fails; that is no scan, not a clean history.
    code, output = run_scan(tmp_path)   # not a repository
    assert code != 0 and "reported an error" in output, output


def test_the_scan_fails_when_gitleaks_is_missing(tmp_path):
    committed_repo(tmp_path, {"a.py": CODE})
    code, output = run_scan(tmp_path, path="/usr/bin:/bin")
    assert code != 0 and "gitleaks is not installed" in output, output


def test_ci_installs_a_pinned_gitleaks_checked_against_its_checksum_before_the_tests():
    install = step_script(f"install gitleaks {GITLEAKS_VERSION}, checked against its published checksum")
    assert f"v{GITLEAKS_VERSION}/gitleaks_{GITLEAKS_VERSION}_linux_x64.tar.gz" in install
    assert "sha256sum -c" in install
    checkout = next(s for s in steps() if s.get("uses", "").startswith("actions/checkout"))
    assert checkout.get("with", {}).get("fetch-depth") == 0   # the scan reads the whole history
    commands = [s.get("run", "") for s in steps()]
    assert commands.index(install) < commands.index(step_script(SCAN_STEP)) < commands.index("python -m pytest -q")


def run_hook(cwd, path, files=None):
    if files is not None:
        subprocess.run(["git", "init", "-q", str(cwd)], check=True)
        for name, body in files.items():
            (cwd / name).write_text(body)
            git(cwd, "add", "-f", name)
    result = subprocess.run([str(HOOK)], check=False, cwd=cwd, capture_output=True, text=True,
                            env={"PATH": path, "HOME": str(cwd)})
    return result.returncode, result.stdout + result.stderr


def gitleaks_path():
    found = shutil.which("gitleaks")
    assert found, "gitleaks is not on PATH; install it as CONTRIBUTING.md 4.4 says"
    return f"{pathlib.Path(found).parent}:/usr/bin:/bin"


def test_the_hook_refuses_a_staged_token_and_names_its_file_redacted(tmp_path):
    code, output = run_hook(tmp_path, gitleaks_path(), {TOKEN_FILE: f'token = "{fake_token()}"\n'})
    assert code != 0 and "gitleaks found a secret" in output, output
    assert TOKEN_FILE in output and fake_token() not in output


def test_the_hook_passes_a_clean_commit(tmp_path):
    code, output = run_hook(tmp_path, gitleaks_path(), {"a.py": CODE})
    assert code == 0, output


def test_the_hook_refuses_when_gitleaks_is_missing(tmp_path):
    code, output = run_hook(tmp_path, "/usr/bin:/bin", {"a.py": CODE})
    assert code != 0 and "gitleaks is not installed" in output, output


def test_the_hook_refuses_when_git_cannot_read_what_is_staged(tmp_path):
    code, output = run_hook(tmp_path, gitleaks_path())   # not a repository
    assert code != 0 and "reported an error" in output, output


# The independent review in CI (CONTRIBUTING.md W6, issue #32): scripts/review.py on the pull request's branch,
# on the Claude subscription. It is not a required check.

REVIEW_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
ISSUE_STEP = "find the issue this pull request closes"


def review_job():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["review"]


def review_step(name):
    matches = [s for s in review_job()["steps"] if s.get("name") == name]
    assert len(matches) == 1, f"expected one review step named {name!r}"
    assert matches[0].get("shell") == "bash"
    return matches[0]


def test_the_review_runs_only_where_the_secret_can_be_read():
    condition = review_job()["if"]
    assert "github.event_name == 'pull_request'" in condition
    assert "github.event.pull_request.head.repo.full_name == github.repository" in condition   # not a fork
    # Who opened it, not who triggered this run: a maintainer's push to Dependabot's branch must not start it.
    assert "github.event.pull_request.user.login != 'dependabot[bot]'" in condition
    assert " || " not in condition   # every condition must hold


def holds(condition, event):
    """Evaluate the job's `if:`: clauses of `a == b` or `a != b` joined by `&&`, against a sample event.

    This is this file's reading of the expression, not GitHub's evaluator: GitHub compares strings without
    regard to case, for one. It catches a dropped, flipped or re-joined clause, which a text match does not.
    """
    def value(term):
        return term.strip("'") if term.startswith("'") else event[term]
    results = []
    for clause in condition.split("&&"):
        left, operator, right = re.fullmatch(r"\s*(\S+)\s*(==|!=)\s*(\S+)\s*", clause).groups()
        results.append((value(left) == value(right)) == (operator == "=="))
    return all(results)


OURS = {"github.event_name": "pull_request", "github.repository": "o/r",
        "github.event.pull_request.head.repo.full_name": "o/r", "github.event.pull_request.user.login": "a-person"}


@pytest.mark.parametrize("label,change,runs", [
    ("a branch of this repository", {}, True),
    ("a fork", {"github.event.pull_request.head.repo.full_name": "someone/r"}, False),
    ("opened by Dependabot", {"github.event.pull_request.user.login": "dependabot[bot]"}, False),
    ("a push to main", {"github.event_name": "push"}, False),
])
def test_the_review_condition_is_evaluated_against_sample_events(label, change, runs):
    assert holds(review_job()["if"], {**OURS, **change}) is runs


def test_the_review_job_can_only_read():
    assert review_job()["permissions"] == {"contents": "read", "issues": "read", "pull-requests": "read"}


def test_the_token_reaches_only_the_step_that_runs_the_review():
    assert WORKFLOW.read_text().count(REVIEW_TOKEN) == 2   # the name and the secret, on one line
    step = review_step("review the branch")
    assert step["env"][REVIEW_TOKEN] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    assert 'python scripts/review.py "$BRANCH" "$ISSUE"' in step["run"]
    assert step["env"]["BRANCH"] == "${{ github.event.pull_request.head.ref }}"   # in env, never in the script
    assert "${{" not in step["run"]
    # The reviewer's own environment holds the subscription token and nothing else that is secret (#35).
    assert sorted(step["env"]) == ["BRANCH", REVIEW_TOKEN, "ISSUE"]
    assert '--issue-file "$RUNNER_TEMP/issue.txt"' in step["run"]


def test_the_issue_text_is_fetched_in_its_own_step_with_the_github_token():
    step = review_step("read the issue")
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}", "ISSUE": "${{ steps.issue.outputs.issue }}"}
    assert step["run"].count('gh issue view "$ISSUE"') == 2 and 'gh issue view "$ISSUE" --comments' in step["run"]
    names = [s.get("name") for s in review_job()["steps"]]
    assert names.index(ISSUE_STEP) < names.index("read the issue") < names.index("review the branch")


def test_the_review_checks_out_the_branch_with_its_history_and_a_pinned_claude_code():
    job = review_job()
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout"))
    # The commit this run is for, then named as the branch, which the script requires. A re-run after a newer
    # push must not review the newer code under the older commit's check.
    # persist-credentials false: the job's token must not sit in .git/config, where the reviewer can read it.
    assert checkout["with"] == {"ref": "${{ github.event.pull_request.head.sha }}", "fetch-depth": 0,
                                "persist-credentials": False}
    name = review_step("name the checkout as the branch")
    assert name["env"] == {"BRANCH": "${{ github.event.pull_request.head.ref }}"}
    commands = [s.get("run", "") for s in job["steps"]]
    assert "npm install --global @anthropic-ai/claude-code@2.1.322" in commands


def name_branch(tmp_path, branch):
    committed_repo(tmp_path, {"a.py": CODE})
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c",
                             review_step("name the checkout as the branch")["run"]],
                            check=False, capture_output=True, text=True, cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin:" + str(pathlib.Path(shutil.which("git")).parent),
                                 "HOME": str(tmp_path), "BRANCH": branch})
    current = subprocess.run(["git", "-C", str(tmp_path), "branch", "--show-current"],
                             check=True, capture_output=True, text=True).stdout.strip()
    return result.returncode, result.stdout + result.stderr, current


def test_the_checkout_is_named_as_the_branch(tmp_path):
    code, output, current = name_branch(tmp_path, "feat/x")
    assert code == 0 and current == "feat/x", output


@pytest.mark.parametrize("branch", ["-f", "--orphan", "-"])
def test_a_branch_name_git_would_read_as_an_option_is_refused(tmp_path, branch):
    code, output, current = name_branch(tmp_path, branch)
    assert code != 0 and "begins with a dash" in output
    assert current != branch


def find_issue(tmp_path, body):
    output = tmp_path / "output"
    output.write_text("")
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", review_step(ISSUE_STEP)["run"]],
                            check=False, capture_output=True, text=True, cwd=tmp_path,
                            env={"PATH": "/usr/bin:/bin:" + str(pathlib.Path(shutil.which("python")).parent),
                                 "BODY": body, "GITHUB_OUTPUT": str(output)})
    return result.returncode, result.stdout + result.stderr, output.read_text()


@pytest.mark.parametrize("body,issue", [("Closes #12\n\nText.", "12"), ("Intro.\ncloses #7\n", "7"),
                                        ("Closes #3\nCloses #4\n", "3")])
def test_the_issue_is_read_from_the_closes_line(tmp_path, body, issue):
    code, output, written = find_issue(tmp_path, body)
    assert code == 0, output
    assert written == f"issue={issue}\n"


@pytest.mark.parametrize("body", ["", "No issue here.", "This mentions Closes #5 mid-line.", "Closes #x"])
def test_a_body_without_a_closes_line_fails_the_job(tmp_path, body):
    code, output, written = find_issue(tmp_path, body)
    assert code != 0 and "no 'Closes #<n>' line" in output
    assert written == ""


def test_the_issue_step_takes_the_body_from_the_environment():
    step = review_step(ISSUE_STEP)
    assert step["env"] == {"BODY": "${{ github.event.pull_request.body }}"} and "${{" not in step["run"]
    assert review_step("review the branch")["env"]["ISSUE"] == "${{ steps.issue.outputs.issue }}" and step["id"] == "issue"


def run_review_step(tmp_path, exit_with, filler=0, char="x"):
    """Run the review step's script with a stand-in for scripts/review.py that prints to both streams and exits."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "review.py").write_text(
        f"import sys\nprint('C3   fail   returns [] on a timeout')\nprint('```text a quoted fence')\n"
        f"print('~' * 12)\nprint('::warning::a forged annotation')\nsys.stdout.flush()\n"
        f"sys.stdout.buffer.write(({char!r} * {filler} + chr(10)).encode('utf-8', 'surrogateescape'))\nprint('the last line')\n"
        f"print('not a complete review: F3: no answer', file=sys.stderr)\nsys.exit({exit_with})\n")
    summary = tmp_path / "summary.md"
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", review_step("review the branch")["run"]],
                            check=False, capture_output=True, text=True, errors="replace", cwd=tmp_path,   # the log is raw
                            env={"PATH": "/usr/bin:/bin:" + str(pathlib.Path(shutil.which("python")).parent),
                                 "BRANCH": "feat/x", "ISSUE": "7", "GITHUB_STEP_SUMMARY": str(summary),
                                 "RUNNER_TEMP": str(tmp_path)})
    return result.returncode, result.stdout + result.stderr, summary.read_bytes().decode("utf-8")   # must be valid


@pytest.mark.parametrize("exit_with", [3, 4, 1])   # fix first, an incomplete report, a crash
def test_a_review_that_does_not_ship_fails_the_step_and_still_reaches_the_summary(tmp_path, exit_with):
    code, log, summary = run_review_step(tmp_path, exit_with)
    assert code == exit_with
    for text in ("C3   fail   returns [] on a timeout", "not a complete review: F3: no answer"):   # stdout and stderr
        assert text in log and text in summary
    # One block, so the lines stay lines. Its fence is tildes, longer than any run of tildes in the report, so
    # neither a quoted ``` fence nor a line of tildes can close it.
    lines = summary.splitlines()
    fence = lines[-1]
    assert set(fence) == {"~"} and len(fence) > 12 and lines[0] == fence + "text"
    assert "```text a quoted fence" in lines and "~" * 12 in lines
    # The report is model output: the runner must not act on a line that looks like a workflow command.
    stop = next(line for line in log.splitlines() if line.startswith("::stop-commands::"))
    token = stop.removeprefix("::stop-commands::")
    assert len(token) >= 32
    assert log.index(stop) < log.index("::warning::a forged annotation") < log.index(f"::{token}::")


def test_a_review_that_ships_passes_the_step(tmp_path):
    assert run_review_step(tmp_path, 0)[0] == 0


def test_a_report_too_big_for_the_summary_is_cut_there_and_whole_in_the_log(tmp_path):
    # GitHub refuses a step summary over about 1 MiB; the upload failing would hide the result.
    code, log, summary = run_review_step(tmp_path, 3, filler=1_200_000)
    assert code == 3
    assert len(summary.encode()) < 1_000_000 and "report cut here" in summary and "the last line" not in summary
    assert "the last line" in log and "C3   fail" in summary
    lines = summary.splitlines()
    assert set(lines[-1]) == {"~"} and lines[0] == lines[-1] + "text"   # still one closed block


@pytest.mark.parametrize("char", ["é", "€", "𝄞"])   # two, three and four bytes: one of them is cut mid-character
def test_a_cut_inside_a_character_leaves_a_valid_summary(tmp_path, char):
    code, _, summary = run_review_step(tmp_path, 3, filler=600_000, char=char)   # run_review_step decodes it
    assert code == 3 and "report cut here" in summary and len(summary.encode()) < 1_000_000


def test_a_byte_that_is_not_utf8_shows_in_the_summary_and_is_not_dropped(tmp_path):
    code, _, summary = run_review_step(tmp_path, 3, filler=1, char="\udcff")   # written as the lone byte 0xff
    assert code == 3 and "\ufffd" in summary and "the last line" in summary


def read_issue(tmp_path, gh_exit, only_comments_fail=False):
    """Run the step that fetches the issue, with a stand-in `gh` that prints its arguments and exits."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fails = 'case "$*" in *--comments*) exit 1 ;; esac\n' if only_comments_fail else ""
    (bin_dir / "gh").write_text(f'#!/bin/sh\necho "gh $*"\n{fails}exit {gh_exit}\n')
    (bin_dir / "gh").chmod(0o755)
    result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", review_step("read the issue")["run"]],
                            check=False, capture_output=True, text=True, cwd=tmp_path,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "ISSUE": "7", "RUNNER_TEMP": str(tmp_path)})
    return result.returncode, (tmp_path / "issue.txt").read_text()


def test_the_issue_step_writes_what_gh_prints_and_fails_when_gh_fails(tmp_path):
    # The body, then the comments, which `gh issue view --comments` prints without the body (#41).
    assert read_issue(tmp_path, 0) == (0, "gh issue view 7\n\nComments on the issue:\ngh issue view 7 --comments\n")
    (tmp_path / "failed").mkdir()
    assert read_issue(tmp_path / "failed", 1)[0] == 1
    # A comments fetch that fails must fail the step: a body with an empty comments section reads as "none" (C3).
    (tmp_path / "comments").mkdir()
    assert read_issue(tmp_path / "comments", 0, only_comments_fail=True)[0] == 1


def test_the_review_job_cannot_hang_or_pile_up():
    job = review_job()
    assert job["timeout-minutes"] == 30
    assert job["concurrency"] == {"group": "review-${{ github.event.pull_request.number }}", "cancel-in-progress": True}
