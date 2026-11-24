"""GitHub through the `gh` CLI (module 7): GitHubTracker and GitHubPullRequests, and FileTracker.

Every call is `gh` as an argument list. The caller can inject `runner`, so tests replay recorded gh output
instead of calling GitHub (module 7: 'GitHub adapters against a recorded gh stub')."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from .adapters.tracker.base import SYNC_LIMIT
from .errors import FactoryError
from .types import PrRef, PrState, Source

Runner = Callable[[list[str]], subprocess.CompletedProcess]

STATUS_LABELS = ("factory:queued", "factory:running", "factory:needs-human", "factory:blocked", "factory:done", "factory:failed",
                 "factory:invalid")
ALL_LABELS = ("factory", *STATUS_LABELS)


def run_gh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def _ok(r: subprocess.CompletedProcess, what: str) -> str:
    if r.returncode == 0:
        return r.stdout
    err = r.stderr.strip()
    if "gh auth login" in err or "authentication" in err.lower() or "401" in err:
        raise FactoryError("git.auth_expired", f"gh {what}: {err[:200]}", hint="run gh auth login, then retry")
    if "rate limit" in err.lower() or "timeout" in err.lower() or "could not resolve" in err.lower() or "connection" in err.lower():
        raise FactoryError("git.network", f"gh {what}: {err[:200]}", hint="a network or rate-limit error; the engine retries with backoff")
    raise FactoryError("git.command_failed", f"gh {what}: {err[:300]}", hint="run the same gh command by hand to reproduce it")


class GitHubTracker:
    """Reads issues labelled `factory` and writes status back as labels and comments (module 4, module 7)."""

    def __init__(self, repo_slug: str | None = None, runner: Runner = run_gh):
        self.repo = repo_slug
        self.run = runner

    def _base(self) -> list[str]:
        return ["-R", self.repo] if self.repo else []

    def list_new(self, since: str | None) -> list[Source]:
        """Every open `factory` issue, up to SYNC_LIMIT. gh returns 30 without --limit, so a 31st queued issue would
        never be read. When the answer holds SYNC_LIMIT issues, intake records the `sync_limit_reached` line in the
        intake log (module 4): this adapter has no run folder and no event log of its own."""
        out = _ok(self.run(["issue", "list", *self._base(), "--label", "factory", "--state", "open",
                            "--limit", str(SYNC_LIMIT), "--json", "number,title,body,labels,author,updatedAt"]),
                  "issue list")
        items = json.loads(out or "[]")
        return [self._source(i) for i in items if since is None or i.get("updatedAt", "") > since]

    def fetch(self, ref: str) -> Source:
        number = _number(ref)
        out = _ok(self.run(["issue", "view", str(number), *self._base(), "--json", "number,title,body,labels,author,updatedAt"]),
                  "issue view")
        return self._source(json.loads(out))

    def _source(self, i: dict) -> Source:
        slug = self.repo or "unknown/unknown"
        return Source(type="github", ref=f"{slug}#{i['number']}", title=i["title"], body=i.get("body") or "",
                      labels=[l["name"] for l in i.get("labels", [])], author=(i.get("author") or {}).get("login"), files=[])

    def set_status(self, ref: str, status: str, *, comment: str | None = None, link: str | None = None) -> None:
        number = str(_number(ref))
        if status not in STATUS_LABELS:
            raise FactoryError("config.invalid", f"unknown status label {status!r}", hint=f"use one of {', '.join(STATUS_LABELS)}")
        remove = [l for l in STATUS_LABELS if l != status]
        _ok(self.run(["issue", "edit", number, *self._base(), "--add-label", status, "--remove-label", ",".join(remove)]), "issue edit")
        if comment:
            body = comment + (f"\n\n{link}" if link else "")
            _ok(self.run(["issue", "comment", number, *self._base(), "--body", body]), "issue comment")

    def ensure_labels(self, labels: list[str]) -> None:
        for label in labels:
            r = self.run(["label", "create", label, *self._base(), "--force"])
            _ok(r, "label create")


def _number(ref: str) -> int:
    m = re.search(r"(\d+)$", ref)
    if not m:
        raise FactoryError("config.invalid", f"cannot read an issue number from {ref!r}", hint="use owner/repo#42 or 42")
    return int(m.group(1))


class GitHubPullRequests:
    def __init__(self, repo_slug: str | None = None, runner: Runner = run_gh):
        self.repo = repo_slug
        self.run = runner

    def _base(self) -> list[str]:
        return ["-R", self.repo] if self.repo else []

    def create(self, worktree: Path, *, base: str, head: str, title: str, body_file: Path, labels: list[str]) -> PrRef:
        args = ["pr", "create", *self._base(), "--base", base, "--head", head, "--title", title, "--body-file", str(body_file)]
        for label in labels:
            args += ["--label", label]
        url = _ok(self.run(args), "pr create").strip().splitlines()[-1]
        return PrRef(number=int(url.rstrip("/").rsplit("/", 1)[-1]), url=url, head=head, base=base)

    def state(self, pr: PrRef) -> PrState:
        out = _ok(self.run(["pr", "view", str(pr.number), *self._base(), "--json", "state,mergeable,reviewDecision,statusCheckRollup"]),
                  "pr view")
        d = json.loads(out)
        state = {"OPEN": "open", "MERGED": "merged", "CLOSED": "closed"}.get(d.get("state", ""), "open")
        ci, tail = ci_from_rollup(d.get("statusCheckRollup") or [])
        return PrState(state=state, ci=ci, checks_output=tail, review_decision=d.get("reviewDecision") or None)  # type: ignore[arg-type]

    def merge(self, pr: PrRef, *, method: str = "squash", auto: bool = True, delete_branch: bool = True) -> None:
        if method not in ("squash", "merge", "rebase"):
            raise FactoryError("config.invalid", f"unknown merge method {method!r}", hint="use squash, merge or rebase")
        args = ["pr", "merge", str(pr.number), *self._base(), f"--{method}"]
        if auto:
            args.append("--auto")
        if delete_branch:
            args.append("--delete-branch")
        _ok(self.run(args), "pr merge")

    def request_reviewers(self, pr: PrRef, users: list[str]) -> None:
        if users:
            _ok(self.run(["pr", "edit", str(pr.number), *self._base(), "--add-reviewer", ",".join(users)]), "pr edit")

    def comment(self, pr: PrRef, body: str) -> None:
        _ok(self.run(["pr", "comment", str(pr.number), *self._base(), "--body", body]), "pr comment")

    def current_user(self) -> str:
        """The login gh is signed in as. It opens the pull requests, so it is the author a review request would target."""
        return _ok(self.run(["api", "user", "-q", ".login"]), "api user").strip()


_FAIL = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
_PASS = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def ci_from_rollup(rollup: list[dict]) -> tuple[str, str]:
    """green, red or pending, from gh's statusCheckRollup. Conservative: a result that is not recognised counts as
    pending, never as green, so an unknown check can never turn into a pass. An empty rollup is pending."""
    if not rollup:
        return "pending", "no checks reported"
    failed, pending, lines = [], [], []
    for c in rollup:
        name = c.get("name") or c.get("context") or "check"
        conclusion = (c.get("conclusion") or c.get("state") or "").upper()
        status = (c.get("status") or "").upper()
        lines.append(f"{name}: {conclusion or status or 'unknown'}")
        if conclusion in _FAIL:
            failed.append(name)
        elif conclusion in _PASS and status in ("", "COMPLETED"):
            continue
        else:
            pending.append(name)
    tail = "\n".join(lines[-200:])
    if failed:
        return "red", tail
    if pending:
        return "pending", tail
    return "green", tail


class FileTracker:
    """The tracker for `tracker: file` (module 4, module 7): requests are markdown files, status goes to front matter.
    No GitHub call is ever made."""

    def __init__(self, inbox: Path):
        self.inbox = inbox
        self.statuses: dict[str, str] = {}

    def list_new(self, since: str | None) -> list[Source]:
        if not self.inbox.is_dir():
            return []
        return [self._read(p) for p in sorted(self.inbox.glob("*.md"))]

    def fetch(self, ref: str) -> Source:
        p = self.inbox / ref
        if not p.is_file():
            raise FactoryError("config.invalid", f"no request file {ref!r} in {self.inbox}", hint="check the file name")
        return self._read(p)

    def _read(self, p: Path) -> Source:
        text = p.read_text()
        title, body, labels = p.stem, text, []
        if text.startswith("---\n") and "\n---\n" in text[4:]:
            front, body = text[4:].split("\n---\n", 1)
            for line in front.splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "title":
                    title = value.strip()
                if key.strip() == "labels":
                    labels = [x.strip() for x in value.strip("[] ").split(",") if x.strip()]
        return Source(type="markdown", ref=p.name, title=title, body=body.strip(), labels=labels, author=None, files=[p])

    def set_status(self, ref: str, status: str, *, comment: str | None = None, link: str | None = None) -> None:
        self.statuses[ref] = status  # recorded in memory; the engine writes the front matter (module 4)

    def ensure_labels(self, labels: list[str]) -> None:
        return None
