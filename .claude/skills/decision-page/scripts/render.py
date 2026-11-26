#!/usr/bin/env python3
"""Render a decisions JSON file to a single self-contained HTML page.

    python3 -I render.py .scratch/<name>.json            -> .scratch/<name>.html
    python3 -I render.py --strict .scratch/<name>.json   -> the same, and exit 1 if anything was warned about

The page exists so a decision can be made and a prompt generated. Only what stops it doing that is an error: a file that
cannot be read, a decision or option with no id, a duplicate id, the id `unsure` (the page uses it), or a decision with no
recommended option. Everything else in SKILL.md (the card cap, the stop trigger, the words in `see`, ids in the question,
option and pro/con counts, the user-side fields) is guidance: it is printed as a warning and the page is still written.
`--strict` turns the warnings back into a failure, for a check that wants the full house style.
"""
import json, re, sys
from pathlib import Path

# Words that name how the factory is built rather than what the user sees. Matched as whole words, case-insensitive.
MECHANISM = ("script", "function", "module", "adapter", "schema", "json", "yaml", "api", "endpoint", "flag", "class",
             "dataclass", "runner", "hook", "regex", "parser", "argparse", "refactor")
# The stop triggers in AGENTS.md (Working rules). A card that meets none of them is decided by the session, not asked.
TRIGGERS = ("reopens-decision", "changes-scope", "costly-to-reverse", "no-clear-winner")
# Guidance: a page holds at most this many cards (docs/process.md, 2026-11-23-cap-a-decision-page-at-five-cards).
MAX_CARDS = 5
INTERNAL_ID = re.compile(r"\b(?:[A-Z]{1,2}\d{1,2}[A-Z]?|module \d+[A-Z]?)\b")

WARNINGS = []

def fail(msg):
    print(f"render: {msg}", file=sys.stderr); sys.exit(1)

def warn(msg):
    WARNINGS.append(msg)
    print(f"render: warning: {msg}", file=sys.stderr)

def has(d, key):
    return isinstance(d.get(key), str) and bool(d[key].strip())

def need(d, key, where, default=None):
    """A text the page can do without: warn, and fill in `default` so the page never prints 'undefined'."""
    if not has(d, key):
        warn(f"{where}: '{key}' is missing" + (f"; using {default!r}" if default is not None else ""))
        if default is not None: d[key] = default

def mechanism_words(s):
    return [w for w in MECHANISM if re.search(rf"\b{w}s?\b", s, re.I)]

def validate(doc):
    if not isinstance(doc, dict): fail("the file must hold one JSON object")
    ds = doc.get("decisions")
    if not isinstance(ds, list) or not ds or not all(isinstance(d, dict) for d in ds):
        fail("page: 'decisions' must be a non-empty list of objects")
    need(doc, "title", "page", "Decisions")
    need(doc, "intro", "page", "")
    need(doc, "target", "page", "the project")
    need(doc, "storage_key", "page", re.sub(r"[^a-z0-9]+", "-", doc["title"].lower()).strip("-") or "decisions")
    if len(ds) > MAX_CARDS:
        warn(f"page: {len(ds)} cards; the guidance is at most {MAX_CARDS} a page, and decide the rest at the "
             "recommendation and log each in docs/decisions.md")
    ids_on_page = {d.get("id") for d in ds}
    seen = set()
    for d in ds:
        if not has(d, "id"): fail("a decision has no 'id'")
        i = d["id"]
        if i in seen: fail(f"{i}: duplicate decision id")
        seen.add(i)
        need(d, "title", i, i)
        for k in ("ref", "why"): need(d, k, i)
        legacy = "context" in d and "today" not in d
        if legacy:
            warn(f"{i}: old shape (one 'context'); write 'question', 'today', 'after' and 'preview' instead")
        else:
            if d.get("trigger") not in TRIGGERS:
                warn(f"{i}: 'trigger' is {d.get('trigger')!r}, not one of {', '.join(TRIGGERS)}; a choice with no stop "
                     "trigger is decided at the recommendation and logged in docs/decisions.md")
            elif not has(d, "trigger_detail"): warn(f"{i}: 'trigger_detail' is missing")
            for k in ("question", "today", "after", "preview"): need(d, k, i)
            if has(d, "question") and not d["question"].rstrip().endswith("?"):
                warn(f"{i}: 'question' should be a question the user would ask")
            for k in ("question", "today", "after"):
                if not has(d, k): continue
                # An id in quotes is the thing being asked about, and one in brackets has its name beside it.
                bare = re.sub(r'"[^"]*"|\([^)]*\)', " ", d[k])
                stray = [m for m in INTERNAL_ID.findall(bare) if m not in ids_on_page]
                if stray: warn(f"{i}: '{k}' names {', '.join(stray)} without saying what it is; use plain words")
        opts = d.get("options")
        if not isinstance(opts, list) or not opts or not all(isinstance(o, dict) for o in opts):
            fail(f"{i}: 'options' must be a non-empty list of objects")
        if not 2 <= len(opts) <= 4: warn(f"{i}: {len(opts)} options; the guidance is 2 to 4")
        ids = set()
        for o in opts:
            if not has(o, "id"): fail(f"{i}: an option has no 'id'")
            oid = o["id"]
            if oid in ids or oid == "unsure": fail(f"{i}/{oid}: duplicate or reserved option id")
            ids.add(oid)
            need(o, "name", f"{i}/{oid}", oid)
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", oid): warn(f"{i}/{oid}: option id should be kebab-case")
            for k in ("pros", "cons"):
                v = o.get(k)
                if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
                    warn(f"{i}/{oid}: '{k}' has no entries")
                    o[k] = [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []
            if legacy: continue
            for k in ("see", "asks"): need(o, k, f"{i}/{oid}")
            if has(o, "see"):
                words = mechanism_words(o["see"])
                if words: warn(f"{i}/{oid}: 'see' says {', '.join(words)}; describe what the user sees, and move how into 'how'")
        n = sum(1 for o in opts if o.get("recommended") is True)
        if n == 0: fail(f"{i}: one option must have \"recommended\": true (the page preselects it and the prompt names it)")
        if n > 1: warn(f"{i}: {n} options are marked recommended; the page preselects the first")

def main():
    args = [a for a in sys.argv[1:] if a != "--strict"]
    strict = len(args) != len(sys.argv) - 1
    if len(args) != 1: fail("usage: render.py [--strict] <decisions.json>")
    src = Path(args[0])
    try: doc = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e: fail(f"cannot read {src}: {e}")
    validate(doc)
    tpl = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
    # '<' is escaped so a decision's text can never close the script tag
    data = json.dumps(doc, ensure_ascii=False).replace("<", "\\u003c")
    html = (tpl.replace("__DATA__", data)
               .replace("__TITLE__", doc["title"].replace("&", "&amp;").replace("<", "&lt;")))
    out = src.with_suffix(".html"); out.write_text(html, encoding="utf-8")
    print(f"render: {len(doc['decisions'])} decisions -> {out}" + (f" ({len(WARNINGS)} warnings)" if WARNINGS else ""))
    if strict and WARNINGS: sys.exit(1)

main()
