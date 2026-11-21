"""A seeded repo for the CLI tests: a git repo with an origin, a services file and a copy of the kit.

It is what `factory init` leaves behind, so `add`, `run` and the other commands work on it as they would in a repo.
"""

import shutil
import subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parents[3]  # factory/


def seed_repo(tmp_path: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "services").mkdir()
    (src / "services" / "api.py").write_text("x = 1\n")
    shutil.copytree(KIT, src / "factory", ignore=shutil.ignore_patterns("engine", ".venv", "__pycache__", "tests"))
    subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   check=True)
    subprocess.run(["git", "-C", str(src), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(src), "push", "-q", "origin", "main"], check=True)
    return src
