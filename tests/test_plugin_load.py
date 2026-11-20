"""Load custom_build the way an agent host does (ARCHITECTURE.md section 1; CONTRIBUTING.md 8 and 8.2).

Each case copies the plugin into a throwaway Hermes home and runs Hermes v0.23.1's ordinary discovery, or
`hermes plugins doctor --ci`, in a process of its own, because Hermes keeps its plugin registry per process.
Needs Hermes importable from the interpreter that runs the tests. The memory-provider loader is not run
yet: the plugin has no provider.
"""

import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "custom_build"

SCENARIO = r"""
import json
from hermes_cli.plugins import discover_plugins, get_plugin_manager

discover_plugins()
print(json.dumps(next((p for p in get_plugin_manager().list_plugins() if p["name"] == "custom_build"), None)))
"""
DOCTOR = "import sys; from hermes_cli.main import main; sys.argv = ['hermes', *sys.argv[1:]]; main()"


def copy_plugin(to):
    shutil.copytree(PLUGIN, to, ignore=shutil.ignore_patterns("__pycache__"))
    return to


def hermes(tmp_path, home, *args):
    env = {"HERMES_HOME": str(home), "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, "-c", *args], capture_output=True, text=True, env=env, cwd=tmp_path,
                          timeout=120, check=False)


def load(tmp_path, manifest_edit=None):
    """Hermes's entry for the plugin after ordinary discovery, with the plugin enabled in a throwaway home."""
    home = tmp_path / "home"
    manifest = copy_plugin(home / "plugins" / "custom_build") / "plugin.yaml"
    if manifest_edit:
        manifest.write_text(manifest_edit(manifest.read_text(encoding="utf-8")), encoding="utf-8")
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - custom_build\n", encoding="utf-8")
    result = hermes(tmp_path, home, SCENARIO)
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def ordinary_load_ok(entry):
    """The ordinary load happened, without an error, as the standalone plugin custom_build."""
    return entry is not None and entry["error"] is None and entry["enabled"] and entry["kind"] == "standalone"


def doctor(tmp_path, plugin_dir):
    """Run `hermes plugins doctor <dir> --ci` with a throwaway home; return its exit code and output."""
    result = hermes(tmp_path, tmp_path / "doctor-home", DOCTOR, "plugins", "doctor", str(plugin_dir), "--ci")
    return result.returncode, result.stdout + result.stderr


def test_ordinary_load_succeeds(tmp_path):
    entry = load(tmp_path)
    assert ordinary_load_ok(entry), entry


def test_a_manifest_without_kind_standalone_fails_the_load_check(tmp_path):
    def drop_kind(text):
        assert "kind: standalone\n" in text
        return text.replace("kind: standalone\n", "")

    assert not ordinary_load_ok(load(tmp_path, manifest_edit=drop_kind))


def test_doctor_passes_the_plugin(tmp_path):
    code, output = doctor(tmp_path, PLUGIN)
    assert code == 0, output
    assert "custom_build" in output and "standalone" in output


def test_doctor_fails_a_plugin_whose_register_raises(tmp_path):
    init = copy_plugin(tmp_path / "custom_build") / "__init__.py"
    text = init.read_text(encoding="utf-8")
    assert "def register(ctx) -> None:\n" in text
    init.write_text(text.replace("def register(ctx) -> None:\n",
                                 "def register(ctx) -> None:\n    raise RuntimeError('broken on purpose')\n"),
                    encoding="utf-8")
    code, output = doctor(tmp_path, tmp_path / "custom_build")
    assert code != 0, output
