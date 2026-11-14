"""Attention items and notifications (module 11).

attention_for() says whether a run needs you. notify() tells you through the request's source (GitHub label and
comment, or markdown front matter), a desktop notification and a webhook. A failed channel is retried and
reported, and never stops the run. Reminders are due again after `remind_after_hours`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import state
from .adapters.tracker.base import TrackerAdapter
from .config import Config
from .decisions import decision_path, kind_of, latest_visit, page_path, try_read
from .types import AttentionItem, Run

DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8765"
DEFAULT_REMIND_AFTER_HOURS = 24
RETRY_DELAYS = (1.0, 5.0)  # seconds between the three tries of one channel

_NEEDS_HUMAN = "factory:needs-human"
_BLOCKED = "factory:blocked"


@dataclass
class NotifyReport:
    sent: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


def _run_dir(run_id: str, repo_key: str | None = None) -> Path | None:
    home = state.factory_home()
    if repo_key is not None:
        return state.run_dir(home, repo_key, run_id)
    ref = state.find_run(home, run_id)
    return ref.run_dir if ref else None


def attention_for(run: Run, *, now: str) -> AttentionItem | None:
    """The attention item a run raises right now, or None. `since` keeps the time the item first appeared."""
    if run.status not in ("awaiting_approval", "blocked"):
        return run.attention if run.attention is not None and run.attention.kind == "request_changed" else None
    stage = next((s.id for s in run.stages if s.status == "awaiting_approval"), run.stage)
    run_dir = _run_dir(run.run_id, run.repo_key)
    visit = latest_visit(run, stage) if stage else 1
    doc = try_read(decision_path(run_dir, stage, visit)) if run_dir is not None and stage else None

    if doc is not None:
        kind = kind_of(doc["packet"])
        first = doc["packet"]["decisions"][0]
        picks = " ".join(f"{d['id']}={d['recommend']}" for d in doc["packet"]["decisions"])
        command = f"factory decide {run.run_id} --stage {stage} --packet {doc['packet']['sha']} {picks}"
        summary = f"{first['title']}: {first['question']}"
        page = page_path(run_dir, stage, visit)
        page = page if page.is_file() else None
    elif run.status == "blocked":
        kind, page = "blocked", None
        command = f"factory retry {run.run_id}"
        summary = f"Run blocked at {stage}: retries or loops ran out"
    elif run.pr is not None:
        kind, page, command = "merge_review", None, None
        summary = f"Pull request #{run.pr.number} waits for review: {run.pr.url}"
    else:
        return None

    prior = run.attention
    since = prior.since if prior is not None and prior.kind == kind and prior.stage == stage else now
    return AttentionItem(kind=kind, run_id=run.run_id, stage=stage, since=since, summary=summary, page=page,  # type: ignore[arg-type]
                         command=command)


def _notify_cfg(cfg: Config) -> dict:
    return (cfg.repo or {}).get("notify") or {}


def _link(item: AttentionItem, cfg: Config) -> str:
    base = str(cfg.machine.get("dashboard_url") or DEFAULT_DASHBOARD_URL).rstrip("/")
    if item.page is not None:
        return f"{base}/runs/{item.run_id}/decisions/{item.page.name}"
    return f"{base}/runs/{item.run_id}"


def _comment(item: AttentionItem, cfg: Config, author: str | None) -> str:
    mention = f"@{author} " if author and _notify_cfg(cfg).get("github_mention", "author") == "author" else ""
    lines = [f"{mention}Run `{item.run_id}` needs you: {item.summary}", "", f"Dashboard: {_link(item, cfg)}"]
    if item.page is not None:
        lines.append(f"Decision page: `{item.page}`")
        lines.append(f"Decision file: `{item.page.with_suffix('.yaml')}`")
    if item.command:
        lines += ["Answer with:", "", f"    {item.command}"]
    return "\n".join(lines)


def _retry(fn) -> None:
    """Three tries with a pause between them; the last error is raised to the caller."""
    for delay in (*RETRY_DELAYS, None):
        try:
            fn()
            return
        except Exception:  # noqa: BLE001  a notification channel may fail in any way
            if delay is None:
                raise
            time.sleep(delay)


def _front_matter(path: Path, status: str, attention: str) -> None:
    text = path.read_text()
    keys = {"factory_status": status, "factory_attention": json.dumps(attention)}
    if text.startswith("---\n") and "\n---\n" in text[4:]:
        front, body = text[4:].split("\n---\n", 1)
        lines = [ln for ln in front.splitlines() if ln.partition(":")[0].strip() not in keys]
    else:
        lines, body = [], text
    lines += [f"{k}: {v}" for k, v in keys.items()]
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body)


def _desktop(title: str, message: str) -> None:
    if sys.platform == "darwin":
        script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
    else:
        subprocess.run(["notify-send", title, message], check=True, capture_output=True, timeout=10)


def _post(url: str, payload: dict) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310  the URL is the operator's own config
        if resp.status >= 400:
            raise OSError(f"webhook answered {resp.status}")


def notify(item: AttentionItem, cfg: Config, tracker: TrackerAdapter) -> NotifyReport:
    """Tell the source, the desktop and the webhook. Each channel is tried three times. Never raises."""
    report = NotifyReport()
    settings = _notify_cfg(cfg)
    run_dir = _run_dir(item.run_id)
    run = _read_run_quietly(run_dir)

    def channel(name: str, fn) -> None:
        try:
            _retry(fn)
            report.sent.append(name)
        except Exception as e:  # noqa: BLE001
            report.failed[name] = str(e)

    if run is not None:
        src = run.request.source
        status = _BLOCKED if item.kind == "blocked" else _NEEDS_HUMAN
        if src.type == "markdown":
            if src.files:
                channel("front_matter", lambda: _front_matter(Path(src.files[0]), "needs-human", item.summary))
        else:
            channel("tracker", lambda: tracker.set_status(src.ref, status, comment=_comment(item, cfg, src.author)))
    if settings.get("desktop"):
        channel("desktop", lambda: _desktop(f"Factory: {item.run_id}", item.summary))
    if settings.get("webhook"):
        payload = {"run_id": item.run_id, "kind": item.kind, "stage": item.stage, "summary": item.summary,
                   "link": _link(item, cfg), "command": item.command}
        channel("webhook", lambda: _post(settings["webhook"], payload))

    if run_dir is not None and run_dir.is_dir():
        state.append_event(run_dir, "attention_notified", kind=item.kind, stage=item.stage, sent=report.sent,
                           failed=report.failed)
    return report


def _read_run_quietly(run_dir: Path | None) -> Run | None:
    if run_dir is None:
        return None
    try:
        return state.read_run(run_dir)
    except Exception:  # noqa: BLE001  an unreadable run must not stop the notification
        return None


def due_reminders(items: list[AttentionItem], cfg: Config, *, now: str) -> list[AttentionItem]:
    """The items whose last notification (or first appearance) is `remind_after_hours` or more behind `now`.
    A value of 0 turns reminders off."""
    hours = _notify_cfg(cfg).get("remind_after_hours", DEFAULT_REMIND_AFTER_HOURS)
    if not hours:
        return []
    limit = timedelta(hours=hours)
    current = _when(now)
    due = []
    for item in items:
        last = _when(item.since)
        run_dir = _run_dir(item.run_id)
        if run_dir is not None:
            stamps = [_when(ev.ts) for ev in state.read_events(run_dir)
                      if ev.type == "attention_notified" and ev.data.get("stage") == item.stage]
            last = max([last, *stamps])
        if current - last >= limit:
            due.append(item)
    return due


def _when(text: str) -> datetime:
    """An ISO time as an aware datetime; a time with no zone is read as UTC."""
    t = datetime.fromisoformat(text)
    return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
