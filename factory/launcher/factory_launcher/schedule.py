"""The OS scheduler entry for `factory tick` (module 6, "Scheduled ticks"): launchd on macOS, a systemd user timer on Linux.

`install` writes the entry and `remove` deletes it. Nothing is loaded into launchd or systemd here: the entry is written
to its path, and the user loads it (`launchctl bootstrap` or `systemctl --user enable --now`). Tests point the path
at a temporary folder. Windows is phase 2.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from pathlib import Path

from factory_engine.errors import FactoryError

LABEL = "com.factory.tick"
UNIT = "factory-tick"
_EVERY = re.compile(r"^(\d+)([smh]?)$")


def interval_seconds(every: str) -> int:
    """'10m' -> 600. A bare number is minutes. Anything else is a config error."""
    m = _EVERY.match(every.strip())
    if not m or int(m.group(1)) <= 0:
        raise FactoryError("config.invalid", f"--every {every!r} is not an interval", hint="use a number with s, m or h, such as 10m")
    n, unit = int(m.group(1)), m.group(2) or "m"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _factory_bin() -> str:
    """The `factory` script on PATH, else this interpreter running the launcher. The scheduler starts with almost no
    PATH, so the entry names an absolute path."""
    found = shutil.which("factory")
    return found if found else f"{sys.executable} -m factory_launcher"


def _log_dir(home: Path) -> Path:
    return home / "logs"


def launchd_plist(every_seconds: int, *, home: Path, binary: str) -> str:
    log = _log_dir(home) / "tick.launchd.log"
    args = "".join(f"    <string>{part}</string>\n" for part in (*binary.split(" "), "tick", "--all-repos"))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n'
        f"  <key>Label</key>\n  <string>{LABEL}</string>\n"
        f"  <key>ProgramArguments</key>\n  <array>\n{args}  </array>\n"
        f"  <key>StartInterval</key>\n  <integer>{every_seconds}</integer>\n"
        f"  <key>StandardOutPath</key>\n  <string>{log}</string>\n"
        f"  <key>StandardErrorPath</key>\n  <string>{log}</string>\n"
        f"  <key>EnvironmentVariables</key>\n  <dict>\n    <key>FACTORY_HOME</key>\n    <string>{home}</string>\n  </dict>\n"
        "</dict>\n</plist>\n"
    )


def systemd_units(every_seconds: int, *, home: Path, binary: str) -> tuple[str, str]:
    """A oneshot service and the timer that starts it. A timer does not start a second run while one is active."""
    service = (
        "[Unit]\nDescription=Factory tick\n\n"
        "[Service]\nType=oneshot\n"
        f"Environment=FACTORY_HOME={home}\n"
        f"ExecStart={binary} tick --all-repos\n"
        f"StandardOutput=append:{_log_dir(home) / 'tick.log'}\n"
        f"StandardError=append:{_log_dir(home) / 'tick.log'}\n"
    )
    timer = (
        "[Unit]\nDescription=Run factory tick every " + f"{every_seconds} seconds\n\n"
        "[Timer]\n"
        "OnBootSec=1min\n"
        f"OnUnitActiveSec={every_seconds}s\n"
        "Persistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    return service, timer


def _system() -> str:
    return "Darwin" if sys.platform == "darwin" else "Linux" if sys.platform.startswith("linux") else platform.system()


def install(every: str, *, home: Path, target_dir: Path | None = None, system: str | None = None) -> Path:
    """Write the OS entry for `factory tick` every `every`. Returns the path written. `target_dir` replaces the real
    LaunchAgents or systemd user folder, so a test can check the content without loading anything."""
    seconds = interval_seconds(every)
    sysname = system or _system()
    binary = _factory_bin()
    _log_dir(home).mkdir(parents=True, exist_ok=True)
    if sysname == "Darwin":
        folder = target_dir or Path.home() / "Library" / "LaunchAgents"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{LABEL}.plist"
        path.write_text(launchd_plist(seconds, home=home, binary=binary))
        return path
    if sysname == "Linux":
        folder = target_dir or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        folder.mkdir(parents=True, exist_ok=True)
        service, timer = systemd_units(seconds, home=home, binary=binary)
        (folder / f"{UNIT}.service").write_text(service)
        path = folder / f"{UNIT}.timer"
        path.write_text(timer)
        return path
    raise FactoryError("config.invalid", f"schedule is not supported on {sysname} in phase 1",
                       hint="Windows is phase 2; run `factory tick` from your own scheduler")


def remove(*, home: Path, target_dir: Path | None = None, system: str | None = None) -> bool:
    """Delete the entry `install` wrote. True when a file was removed."""
    sysname = system or _system()
    if sysname == "Darwin":
        path = (target_dir or Path.home() / "Library" / "LaunchAgents") / f"{LABEL}.plist"
        return _unlink(path)
    if sysname == "Linux":
        folder = target_dir or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        a = _unlink(folder / f"{UNIT}.timer")
        b = _unlink(folder / f"{UNIT}.service")
        return a or b
    raise FactoryError("config.invalid", f"schedule is not supported on {sysname} in phase 1", hint="Windows is phase 2")


def _unlink(path: Path) -> bool:
    if path.is_file():
        path.unlink()
        return True
    return False
