"""Module 16: a launcher run by a Python that cannot import the engine's runtime dependencies stops with a named error
and the shared exit code, not a traceback from inside the engine. The check runs in the package `__init__`, so every
launcher entry point (`python -m factory_launcher`, the `factory` script, the dashboard server) gets it."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("dependency", ["yaml", "jsonschema"])
def test_a_python_without_a_runtime_dependency_stops_with_a_named_error_and_no_traceback(dependency):
    code = (
        "import runpy, sys\n"
        f"sys.modules[{dependency!r}] = None\n"  # makes `import <dependency>` fail, as on an interpreter without it
        "sys.argv = ['factory', 'doctor', '--no-repo']\n"
        "runpy.run_module('factory_launcher.__main__', run_name='__main__')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stderr.startswith(f"config.invalid: {sys.executable} cannot import {dependency}"), proc.stderr
    assert "\nhint: install" in proc.stderr, proc.stderr
    assert proc.stdout == ""


def test_with_json_the_named_error_is_the_shared_error_shape_on_stdout():
    import json

    code = (
        "import runpy, sys\n"
        "sys.modules['yaml'] = None\n"
        "sys.argv = ['factory', 'doctor', '--no-repo', '--json']\n"
        "runpy.run_module('factory_launcher.__main__', run_name='__main__')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, proc.stderr
    body = json.loads(proc.stdout)
    assert body["ok"] is False and body["code"] == "config.invalid" and body["data"] == {}
    assert "yaml" in body["message"] and body["hint"].startswith("install")
    assert "Traceback" not in proc.stderr
