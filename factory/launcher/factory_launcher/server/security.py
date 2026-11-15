"""Request checks (module 15): the Host, the Origin and the session token. Each returns a bool and changes nothing."""

from __future__ import annotations

import secrets

TOKEN_HEADER = "X-Factory-Token"


def new_token() -> str:
    """A new token at each start, so a bookmark from an earlier start stops working."""
    return secrets.token_urlsafe(32)


def host_ok(host: str | None, port: int) -> bool:
    """Only the configured dashboard address. A page on another host name, reached through DNS rebinding, fails here."""
    return host == f"127.0.0.1:{port}"


def origin_ok(origin: str | None, port: int) -> bool:
    """A POST must come from the dashboard itself. A POST without an Origin is refused too."""
    return origin == f"http://127.0.0.1:{port}"


def token_ok(presented: str | None, token: str) -> bool:
    if not presented:
        return False
    return secrets.compare_digest(presented.encode(), token.encode())
