"""FakePullRequests: an in-memory pull request service for other modules' tests (module 7).

A test moves a PR through its life with set_ci(), human_merge() and close(). With auto=True, merge() only
turns on auto-merge, as GitHub does: the PR merges when CI is green. fail_next raises once on the next call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .types import PrRef, PrState


@dataclass
class _Pr:
    ref: PrRef
    title: str
    body: str
    labels: list[str]
    state: str = "open"
    ci: str = "pending"
    checks_output: str = ""
    review_decision: str | None = None
    auto_merge: bool = False
    reviewers: list[str] = field(default_factory=list)
    merged_with: str | None = None


class FakePullRequests:
    def __init__(self):
        self.prs: dict[int, _Pr] = {}
        self.fail_next: Exception | None = None
        self.calls: list[str] = []

    def _maybe_fail(self) -> None:
        if self.fail_next is not None:
            err, self.fail_next = self.fail_next, None
            raise err

    def _get(self, pr: PrRef) -> _Pr:
        try:
            return self.prs[pr.number]
        except KeyError:
            raise KeyError(f"no pull request #{pr.number}") from None

    def create(self, worktree: Path, *, base: str, head: str, title: str, body_file: Path,
               labels: list[str]) -> PrRef:
        self.calls.append("create")
        self._maybe_fail()
        number = len(self.prs) + 1
        ref = PrRef(number=number, url=f"https://example.invalid/pull/{number}", head=head, base=base)
        self.prs[number] = _Pr(ref, title, Path(body_file).read_text(), list(labels))
        return ref

    def state(self, pr: PrRef) -> PrState:
        self.calls.append("state")
        self._maybe_fail()
        p = self._get(pr)
        return PrState(p.state, p.ci, p.checks_output, p.review_decision)  # type: ignore[arg-type]

    def merge(self, pr: PrRef, *, method: str = "squash", auto: bool = True, delete_branch: bool = True) -> None:
        self.calls.append("merge")
        self._maybe_fail()
        p = self._get(pr)
        if p.state != "open":
            raise RuntimeError(f"pull request #{pr.number} is {p.state}")
        p.merged_with = method
        if auto:
            p.auto_merge = True
            if p.ci == "green":
                p.state = "merged"
        else:
            if p.ci != "green":
                raise RuntimeError(f"pull request #{pr.number} has CI {p.ci}")
            p.state = "merged"

    def request_reviewers(self, pr: PrRef, users: list[str]) -> None:
        self.calls.append("request_reviewers")
        self._maybe_fail()
        self._get(pr).reviewers.extend(users)

    # Test controls (not part of the PullRequests protocol).
    def set_ci(self, pr: PrRef, ci: str, output: str = "") -> None:
        p = self._get(pr)
        p.ci, p.checks_output = ci, output
        if ci == "green" and p.auto_merge and p.state == "open":
            p.state = "merged"

    def human_merge(self, pr: PrRef) -> None:
        self._get(pr).state = "merged"

    def close(self, pr: PrRef) -> None:
        self._get(pr).state = "closed"
