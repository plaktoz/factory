"""Module 5: the exit codes of `python -m factory_engine.plugin_runner` (0 passed, 1 check failed, 2 task error).

These run the runner directly in a subprocess, with no sandbox, so they need neither srt nor Node.
"""

import json
import subprocess
import sys

import pytest


def run_runner(tmp_path, source, stdin="{}"):
    (tmp_path / "plug.py").write_text(source)
    proc = subprocess.run([sys.executable, "-m", "factory_engine.plugin_runner", str(tmp_path), "plug:check"],
                          input=stdin, capture_output=True, text=True, timeout=60)
    return proc.returncode, proc.stdout


def test_a_result_with_passed_false_and_no_status_is_a_check_failure(tmp_path):
    code, out = run_runner(tmp_path, "def check(ctx):\n    return {'passed': False}\n")
    assert code == 1
    assert json.loads(out)["passed"] is False


def test_a_result_with_passed_true_and_no_status_passes(tmp_path):
    code, _ = run_runner(tmp_path, "def check(ctx):\n    return {'passed': True}\n")
    assert code == 0


def test_a_syntax_error_at_import_is_a_task_error(tmp_path):
    code, out = run_runner(tmp_path, "def check(ctx:\n    return True\n")
    assert code == 2
    assert "cannot be imported" in json.loads(out)["error"]


@pytest.mark.parametrize("body", ["raise RuntimeError('boom')", "import sys\nsys.exit(1)"])
def test_any_other_error_raised_at_import_is_a_task_error(tmp_path, body):
    code, out = run_runner(tmp_path, f"{body}\ndef check(ctx):\n    return True\n")
    assert code == 2
    assert "cannot be imported" in json.loads(out)["error"]


def test_a_result_that_cannot_be_written_as_json_is_a_task_error(tmp_path):
    code, _ = run_runner(tmp_path, "def check(ctx):\n    return {'passed': True, 'found': {1, 2}}\n")
    assert code == 2


@pytest.mark.parametrize("code", [0, 1])
def test_sys_exit_inside_the_function_is_a_task_error(tmp_path, code):
    code_out, out = run_runner(tmp_path, f"import sys\ndef check(ctx):\n    sys.exit({code})\n")
    assert code_out == 2
    assert "SystemExit" in json.loads(out)["error"]


def test_a_function_that_raises_is_a_task_error(tmp_path):
    code, out = run_runner(tmp_path, "def check(ctx):\n    raise RuntimeError('boom')\n")
    assert code == 2
    assert "RuntimeError: boom" in json.loads(out)["error"]
