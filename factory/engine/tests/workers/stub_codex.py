#!/usr/bin/env python3
"""A stub `codex` for the adapter tests. It replays a recorded JSONL event stream and records what it was asked to do.

Its behaviour comes from a JSON file, written by the test next to the stub and passed as argv[1]. The rest of argv is
what the adapter gave the worker. The stub runs under srt, so it writes its record only into the task folder. It never
talks to a network.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    if sys.argv[2:] == ["--version"]:
        sys.stdout.write("codex-cli 0.164.0\n")
        return 0
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
        if "CODEX_HOME" in os.environ:
            (rec / "codex-home.txt").write_text(json.dumps(sorted(os.listdir(os.environ["CODEX_HOME"]))))

    probes = {}
    for target in cfg.get("writes", []):
        try:
            Path(target).write_text("probe\n")
            probes[target] = "written"
        except OSError:
            probes[target] = "refused"
    if rec is not None:
        (rec / "writes.json").write_text(json.dumps(probes))

    pids = []
    for _ in range(int(cfg.get("helpers", 0))):
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
