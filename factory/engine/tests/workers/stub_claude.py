#!/usr/bin/env python3
"""A stub `claude` for the adapter tests. It replays a recorded JSON result and records what it was asked to do.

Its behaviour comes from a JSON file, STUB_CONFIG, that the test writes next to the stub. The adapter gives the worker
only its declared environment (module 9), so the stub cannot read settings from environment variables. Keys are listed
in `conftest.write_stub_config`. The stub never talks to a network. What it records is the adapter's real output.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def arg_value(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main():
    # argv[1] is the config path the test's wrapper passes; the rest is what the adapter gave the worker.
    cfg = json.loads(Path(sys.argv[1]).read_text())
    rec = Path(cfg["record"]) if cfg.get("record") else None
    argv = sys.argv[2:]
    prompt = sys.stdin.read()
    if rec is not None:
        rec.mkdir(parents=True, exist_ok=True)
        (rec / "argv.txt").write_text("\n".join(argv) + "\n")
        (rec / "cwd.txt").write_text(os.getcwd() + "\n")
        (rec / "env.json").write_text(json.dumps(dict(os.environ)))
        (rec / "prompt.txt").write_text(prompt)
        for flag, name in (("--settings", "settings.json"), ("--mcp-config", "mcp.json")):
            src = arg_value(argv, flag)
            if src:
                shutil.copy(src, rec / name)

    helpers = int(cfg.get("helpers", 0))
    pids = []
    for _ in range(helpers):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        pids.append(p.pid)
    if pids and rec is not None:
        (rec / "helper-pids.txt").write_text("\n".join(map(str, pids)) + "\n")

    if cfg.get("early_out"):  # printed before the sleep, so a test can read worker.log while the worker runs
        sys.stdout.write(cfg["early_out"] + "\n")
        sys.stdout.flush()
    if cfg.get("early_err"):
        sys.stderr.write(cfg["early_err"] + "\n")
        sys.stderr.flush()
    if cfg.get("sleep"):
        time.sleep(float(cfg["sleep"]))

    if cfg.get("artifact"):
        name, text = cfg["artifact"]
        task_dir = Path(os.environ["FACTORY_TASK_DIR"])
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / name).write_text(text)

    sys.stdout.write(Path(cfg["result"]).read_text())
    if cfg.get("stderr"):
        sys.stderr.write(cfg["stderr"] + "\n")
    return int(cfg.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
