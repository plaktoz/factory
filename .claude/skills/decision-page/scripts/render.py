#!/usr/bin/env python3
"""Render a decisions JSON file to a single self-contained HTML page.

    python3 -I render.py docs/decision-pages/<name>.json      -> docs/decision-pages/<name>.html

Validates the schema in SKILL.md and exits non-zero on any problem. A page in the old shape (a single `context`, no
`see` or `asks` per option) still renders, with a warning, so pages already answered stay readable.
"""
import json, re, sys
from pathlib import Path

# Words that name how the factory is built rather than what the user sees. The first line of an option (`see`) is
# the user's view, so these belong in `how`. Matched as whole words, case-insensitive.
MECHANISM = ("script", "function", "module", "adapter", "schema", "json", "yaml", "api", "endpoint", "flag", "class",
             "dataclass", "runner", "hook", "regex", "parser", "argparse", "refactor")
# "commit" is not on the list: in a repo it is something the user does, not how the tool works inside.
INTERNAL_ID = re.compile(r"\b(?:[A-Z]{1,2}\d{1,2}[A-Z]?|module \d+[A-Z]?)\b")

def fail(msg):
    print(f"render: {msg}", file=sys.stderr); sys.exit(1)

def warn(msg):
    print(f"render: warning: {msg}", file=sys.stderr)

def text(d, key, where):
    v = d.get(key)
    if not isinstance(v, str) or not v.strip(): fail(f"{where}: '{key}' must be a non-empty string")
    return v

def mechanism_words(s):
    return [w for w in MECHANISM if re.search(rf"\b{w}s?\b", s, re.I)]

def validate(doc):
    for k in ("title", "intro", "target", "storage_key"): text(doc, k, "page")
    ds = doc.get("decisions")
    if not isinstance(ds, list) or not ds: fail("page: 'decisions' must be a non-empty list")
    ids_on_page = {d.get("id") for d in ds}
    seen = set()
    for d in ds:
        i = text(d, "id", "decision")
        if i in seen: fail(f"{i}: duplicate decision id")
        seen.add(i)
        for k in ("title", "ref", "why"): text(d, k, i)
        legacy = "context" in d and "today" not in d
        if legacy:
            text(d, "context", i)
            warn(f"{i}: old shape (one 'context'); write 'question', 'today', 'after' and 'preview' instead")
        else:
            for k in ("question", "today", "after", "preview"): text(d, k, i)
            if not d["question"].rstrip().endswith("?"): fail(f"{i}: 'question' must be a question the user would ask")
            for k in ("question", "today", "after"):
                # An id in quotes is the thing being asked about, and one in brackets has its name beside it.
                bare = re.sub(r'"[^"]*"|\([^)]*\)', " ", d[k])
                stray = [m for m in INTERNAL_ID.findall(bare) if m not in ids_on_page]
                if stray: fail(f"{i}: '{k}' names {', '.join(stray)} without saying what it is; use plain words")
        opts = d.get("options")
        if not isinstance(opts, list) or not 2 <= len(opts) <= 4: fail(f"{i}: needs 2 to 4 options")
        ids = set()
        for o in opts:
            oid = text(o, "id", i); text(o, "name", f"{i}/{oid}")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", oid): fail(f"{i}/{oid}: option id must be kebab-case")
            if oid in ids or oid == "unsure": fail(f"{i}/{oid}: duplicate or reserved option id")
            ids.add(oid)
            for k in ("pros", "cons"):
                v = o.get(k)
                if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
                    fail(f"{i}/{oid}: '{k}' needs at least one non-empty string")
            if legacy:
                continue
            for k in ("see", "asks"): text(o, k, f"{i}/{oid}")
            words = mechanism_words(o["see"])
            if words: fail(f"{i}/{oid}: 'see' says {', '.join(words)}; describe what the user sees, and move how into 'how'")
            if "how" in o: text(o, "how", f"{i}/{oid}")
        if sum(1 for o in opts if o.get("recommended") is True) != 1:
            fail(f"{i}: exactly one option must have \"recommended\": true")

def main():
    if len(sys.argv) != 2: fail("usage: render.py <decisions.json>")
    src = Path(sys.argv[1])
    try: doc = json.loads(src.read_text(encoding="utf-8"))
    except Exception as e: fail(f"cannot read {src}: {e}")
    validate(doc)
    tpl = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")
    # '<' is escaped so a decision's text can never close the script tag
    data = json.dumps(doc, ensure_ascii=False).replace("<", "\\u003c")
    html = (tpl.replace("__DATA__", data)
               .replace("__TITLE__", doc["title"].replace("&", "&amp;").replace("<", "&lt;")))
    out = src.with_suffix(".html"); out.write_text(html, encoding="utf-8")
    print(f"render: {len(doc['decisions'])} decisions -> {out}")

main()
