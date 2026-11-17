"""Acceptance-criteria gate for one module (the definition of done in AGENTS.md).

Run from the repo root: python3 -I scripts/docs-check/criteria.py . <module number or file>
With no module, prints the count for every module and exits 0.

A module passes only when every `- [ ]` / `- [x]` line in its file is ticked and each tick
names a test path that exists (`...::test_name` or a `tests/...py` path). A criterion that
cannot be ticked must say `(not ticked: reason)`; the module is then not done.
"""
import re, sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
want = sys.argv[2] if len(sys.argv) > 2 else None
mods = sorted((root / "docs/design/modules").glob("*.md"))
TEST = re.compile(r"(?:factory/engine/|factory/launcher/|scripts/docs-check/)?(?:tests?/[\w/.\-]+\.py)")
status = 0

for f in mods:
    if want and not (f.name.startswith(want.zfill(2)) or f.name == want or str(f) == want):
        continue
    lines = [l for l in f.read_text(encoding="utf-8").splitlines() if re.match(r"- \[[ x]\] ", l)]
    ticked = [l for l in lines if l.startswith("- [x]")]
    open_ = [l for l in lines if l.startswith("- [ ]")]
    no_test = [l for l in ticked if not TEST.search(l)]
    no_reason = [l for l in open_ if "not ticked" not in l]
    print(f"{f.name}: {len(ticked)} ticked, {len(open_)} open, {len(no_test)} ticked without a test path, "
          f"{len(no_reason)} open without a reason")
    if want:
        for l in open_ + no_test:
            print("   -", l[:140])
        if open_ or no_test:
            status = 1
sys.exit(status)
