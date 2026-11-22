"""The OS scheduler entry for `factory tick` (module 6, "Scheduled ticks"): launchd on macOS, a systemd user timer on Linux.

`install` writes the entry and `remove` deletes it. Nothing is loaded into launchd or systemd here: the entry is written
to its path, and the user loads it (`launchctl bootstrap` or `systemctl --user enable --now`). Tests point the path
at a temporary folder. Windows is phase 2.

`install_once` and `remove_once` do the same for a named job that runs one command once, at a local time (module 16,
`factory schedule at`). It survives the end of the session that asked for it, which a session's own timer does not.
"""

from __future__ import annotations

import os
import platform
import plistlib
import re
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

from factory_engine.errors import FactoryError

LABEL = "com.factory.tick"
UNIT = "factory-tick"
_EVERY = re.compile(r"^(\d+)([smh]?)$")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def interval_seconds(every: str) -> int:
    """'10m' -> 600. A bare number is minutes. Anything else is a config error."""
    m = _EVERY.match(every.strip())
    if not m or int(m.group(1)) <= 0:
        raise FactoryError("config.invalid", f"--every {every!r} is not an interval", hint="use a number with s, m or h, such as 10m")
    n, unit = int(m.group(1)), m.group(2) or "m"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _factory_command() -> list[str]:
    """The `factory` script on PATH, else this interpreter running the launcher. The scheduler starts with almost no
    PATH, so the entry names an absolute path. A list, so an interpreter path with spaces stays one argument."""
    found = shutil.which("factory")
    return [found] if found else [sys.executable, "-m", "factory_launcher"]


def _log_dir(home: Path) -> Path:
    return home / "logs"


def launchd_plist(every_seconds: int, *, home: Path, command: list[str]) -> str:
    log = _log_dir(home) / "tick.launchd.log"
    args = "".join(f"    <string>{part}</string>\n" for part in (*command, "tick", "--all-repos"))
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


def systemd_units(every_seconds: int, *, home: Path, command: list[str]) -> tuple[str, str]:
    """A oneshot service and the timer that starts it. A timer does not start a second run while one is active."""
    service = (
        "[Unit]\nDescription=Factory tick\n\n"
        "[Service]\nType=oneshot\n"
        f"Environment=FACTORY_HOME={home}\n"
        f"ExecStart={' '.join(command)} tick --all-repos\n"
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
    command = _factory_command()
    _log_dir(home).mkdir(parents=True, exist_ok=True)
    if sysname == "Darwin":
        folder = target_dir or Path.home() / "Library" / "LaunchAgents"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{LABEL}.plist"
        path.write_text(launchd_plist(seconds, home=home, command=command))
        return path
    if sysname == "Linux":
        folder = target_dir or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        folder.mkdir(parents=True, exist_ok=True)
        service, timer = systemd_units(seconds, home=home, command=command)
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


def once_label(name: str) -> str:
    return f"com.factory.once.{name}"


def _check_name(name: str) -> None:
    if not _NAME.match(name):
        raise FactoryError("config.invalid", f"--name {name!r} is not a job name", hint="use lower-case letters, digits and hyphens")


def _local(at: datetime) -> datetime:
    return at.astimezone().replace(tzinfo=None) if at.tzinfo else at


def parse_at(text: str, *, now: datetime | None = None) -> datetime:
    """'2026-11-25T19:43' -> a naive local time. A time with an offset is converted to local. A time not in the future,
    or not a time, is a config error: launchd would run a past calendar entry next year."""
    try:
        at = _local(datetime.fromisoformat(text.strip()))
    except ValueError:
        raise FactoryError("config.invalid", f"--at {text!r} is not a time", hint="use a local time such as 2026-11-25T19:43") from None
    if at <= (now or datetime.now()):
        raise FactoryError("config.invalid", f"--at {text!r} is not in the future", hint="give a time after now")
    return at


def _agents_folder(sysname: str, target_dir: Path | None) -> Path:
    if sysname == "Darwin":
        return target_dir or Path.home() / "Library" / "LaunchAgents"
    return target_dir or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"


def _once_unsupported(sysname: str) -> FactoryError:
    return FactoryError("config.invalid", f"schedule is not supported on {sysname} in phase 1", hint="Windows is phase 2")


def launchd_once_plist(name: str, at: datetime, command: list[str], *, home: Path, cwd: Path, path: Path) -> bytes:
    """The job runs `command`, then deletes its own entry and unloads itself. Without that, launchd would run it again
    on the same date next year, because a calendar entry has no year."""
    label = once_label(name)
    log = _log_dir(home) / f"once-{name}.log"
    wrapper = f'"$@"; rc=$?; rm -f {shlex.quote(str(path))}; launchctl bootout "gui/$(id -u)/{label}" 2>/dev/null; exit $rc'
    return plistlib.dumps({
        "Label": label,
        "ProgramArguments": ["/bin/sh", "-c", wrapper, "factory-once", *command],
        "StartCalendarInterval": {"Month": at.month, "Day": at.day, "Hour": at.hour, "Minute": at.minute},
        "WorkingDirectory": str(cwd),
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": {"FACTORY_HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    })


def systemd_once_units(name: str, at: datetime, command: list[str], *, home: Path, cwd: Path) -> tuple[str, str]:
    log = _log_dir(home) / f"once-{name}.log"
    service = (
        f"[Unit]\nDescription=Factory one-off job {name}\n\n"
        "[Service]\nType=oneshot\n"
        f"WorkingDirectory={cwd}\n"
        f"Environment=FACTORY_HOME={home}\n"
        f"Environment=PATH={os.environ.get('PATH', '/usr/bin:/bin')}\n"
        f"ExecStart={shlex.join(command)}\n"
        f"StandardOutput=append:{log}\nStandardError=append:{log}\n"
    )
    timer = (
        f"[Unit]\nDescription=Run factory one-off job {name}\n\n"
        f"[Timer]\nOnCalendar={at:%Y-%m-%d %H:%M:%S}\nPersistent=true\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    return service, timer


def install_once(name: str, at: datetime, command: list[str], *, home: Path, cwd: Path,
                 target_dir: Path | None = None, system: str | None = None) -> Path:
    """Write the OS entry that runs `command` once at the local time `at`, from the folder `cwd`. The program is
    resolved to an absolute path now, because the scheduler starts with almost no PATH. Returns the path written."""
    _check_name(name)
    if not command:
        raise FactoryError("config.invalid", "no command to run", hint="give the command after --")
    program = shutil.which(command[0])
    if program is None:
        raise FactoryError("config.invalid", f"{command[0]!r} is not on PATH", hint="give a program that exists")
    command = [program, *command[1:]]
    sysname = system or _system()
    if sysname not in ("Darwin", "Linux"):
        raise _once_unsupported(sysname)
    folder = _agents_folder(sysname, target_dir)
    folder.mkdir(parents=True, exist_ok=True)
    _log_dir(home).mkdir(parents=True, exist_ok=True)
    if sysname == "Darwin":
        path = folder / f"{once_label(name)}.plist"
        path.write_bytes(launchd_once_plist(name, at, command, home=home, cwd=cwd, path=path))
        return path
    service, timer = systemd_once_units(name, at, command, home=home, cwd=cwd)
    (folder / f"{UNIT}-once-{name}.service").write_text(service)
    path = folder / f"{UNIT}-once-{name}.timer"
    path.write_text(timer)
    return path


def remove_once(name: str, *, target_dir: Path | None = None, system: str | None = None) -> bool:
    """Delete the entry `install_once` wrote for `name`. True when a file was removed."""
    _check_name(name)
    sysname = system or _system()
    if sysname not in ("Darwin", "Linux"):
        raise _once_unsupported(sysname)
    folder = _agents_folder(sysname, target_dir)
    if sysname == "Darwin":
        return _unlink(folder / f"{once_label(name)}.plist")
    a = _unlink(folder / f"{UNIT}-once-{name}.timer")
    b = _unlink(folder / f"{UNIT}-once-{name}.service")
    return a or b
