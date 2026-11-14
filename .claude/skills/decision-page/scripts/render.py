#!/usr/bin/env python3
"""Render a decisions JSON file to a single self-contained HTML page.

    python3 -I render.py docs/reviews/<name>.json      -> docs/reviews/<name>.html

Validates the schema in SKILL.md and exits non-zero on any problem.
"""
import json, re, sys
from pathlib import Path

def fail(msg):
    print(f"render: {msg}", file=sys.stderr); sys.exit(1)

def text(d, key, where):
    v = d.get(key)
    if not isinstance(v, str) or not v.strip(): fail(f"{where}: '{key}' must be a non-empty string")
    return v

def validate(doc):
    for k in ("title", "intro", "target", "storage_key"): text(doc, k, "page")
    ds = doc.get("decisions")
    if not isinstance(ds, list) or not ds: fail("page: 'decisions' must be a non-empty list")
    seen = set()
    for d in ds:
        i = text(d, "id", "decision")
        if i in seen: fail(f"{i}: duplicate decision id")
        seen.add(i)
        for k in ("title", "ref", "context", "why"): text(d, k, i)
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
