"""mask(text, secrets) (module 3): resolved secret values become *** in logs, events and feedback."""

from __future__ import annotations

from collections.abc import Iterable


def mask(text: str, secrets: Iterable[str]) -> str:
    # longest first, so a secret that contains another is masked whole
    for s in sorted({x for x in secrets if x}, key=len, reverse=True):
        text = text.replace(s, "***")
    return text
