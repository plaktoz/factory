"""Dashboard settings (module 15): the factory home, the port, and the display and health settings from the machine
config (`show_finished_days`, `tick: {every_minutes, stale_after_ticks}`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from factory_engine.loadcfg import load_config

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parents[3] / "dashboard"


@dataclass(frozen=True)
class Settings:
    home: Path
    port: int = DEFAULT_PORT
    show_finished_days: int = 7
    tick_every_minutes: float = 10.0
    stale_after_ticks: int = 3
    static_dir: Path = STATIC_DIR


def settings_from_home(home: Path, *, port: int = DEFAULT_PORT) -> Settings:
    machine = load_config(None, env={"FACTORY_HOME": str(home)}).machine
    tick = machine.get("tick") or {}
    return Settings(home=home, port=port,
                    show_finished_days=int(machine.get("show_finished_days", 7)),
                    tick_every_minutes=float(tick.get("every_minutes", 10)),
                    stale_after_ticks=int(tick.get("stale_after_ticks", 3)))
