"""A seeded repo for the CLI tests: a git repo with an origin, a services file and a copy of the kit.

It is what `factory init` leaves behind, so `add`, `run` and the other commands work on it as they would in a repo.
"""

import shutil
import subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parents[3]  # factory/
_SKIP = {"engine", ".venv", "__pycache__", "tests"}  # top level of the kit only, as `factory init` leaves it


def seed_repo(tmp_path: Path) -> Path:
    src = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    (src / "services").mkdir()
    (src / "services" / "api.py").write_text("x = 1\n")
    shutil.copytree(KIT, src / "factory", symlinks=True,
                    ignore=lambda d, names: _SKIP & set(names) if Path(d) == KIT else set())
    subprocess.run(["git", "-C", str(src), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                   check=True)
    # A bare clone and a fetch give origin/main without a push: the managed pre-push scan costs ~20 s per push.
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(bare)], check=True)
    subprocess.run(["git", "-C", str(src), "remote", "add", "origin", str(bare)], check=True)
    subprocess.run(["git", "-C", str(src), "fetch", "-q", "origin"], check=True)
    return src
