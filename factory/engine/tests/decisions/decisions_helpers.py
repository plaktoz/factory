"""Plain helpers for the decisions tests. Fixtures stay in conftest.py; tests import these by their own module name."""

import copy

from factory_engine import state
from factory_engine.lock import acquire_lock, release
from factory_engine.types import Request, Source, StageState


def make_request(source_type="github", ref="acme/report#42", author="alice", files=None):
    return Request(request_id="gh-42", source=Source(source_type, ref, "Login fails", "body", ["bug"], author, files or []),
                   body_sha="c91e07", repo="report", title="Login fails", type="bug", type_source="label",
                   priority="high", acceptance=["401 with a refresh hint"])


def set_run(ref, *, status, stage, stages=None, attention=None, pr=None):
    """Write run.json the way the lock holder does."""
    r = state.read_run(ref.run_dir)
    r.status, r.stage = status, stage
    r.stages = stages if stages is not None else [StageState(stage, 1, "awaiting_approval", [], "t0", None)]
    r.attention = attention
    r.pr = pr
    lock = acquire_lock(ref.run_dir, "engine")
    state.write_run(ref.run_dir, r, lock=lock)
    release(lock)
    return r


def option(oid, name=None, **kw):
    return {"id": oid, "name": name or oid, "flow": ["human:Request", "code:Build"], "pros": ["Fast"],
            "cons": ["New"], **kw}


def decision(did="D1", **kw):
    d = {"id": did, "title": "Frontend stack", "question": "Which frontend stack?",
         "context": {"what": "A reports UI.", "example": "Finance filters patch data.", "terms": {"SPA": "single-page app"}},
         "compare": {"a": "opt-a", "b": "opt-b", "rows": [["Interactivity", "High", "Low"]],
                     "choose_a_if": "Users filter", "choose_b_if": "Static tables"},
         "recommend": "opt-a", "why": "Fits the team.",
         "options": [option("opt-a", "React"), option("opt-b", "Server pages")]}
    d.update(kw)
    return d


def architect_packet(*decisions):
    return {"stage": "architecture", "sha": "", "decisions": list(decisions) or [decision(), decision("D2")]}


def without(packet, *path):
    """A deep copy of the packet with the key at `path` removed."""
    p = copy.deepcopy(packet)
    node = p
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return p
