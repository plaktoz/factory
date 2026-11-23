"""Tests for render.py. Run: python3 -I -m unittest .claude/skills/decision-page/scripts/test_render.py"""
import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

RENDER = Path(__file__).with_name("render.py")

CARD = {
    "id": "D1", "title": "Branch name", "ref": "Working rules",
    "trigger": "reopens-decision", "trigger_detail": "Changes the naming rule in the branch ADR of 2026-11-14.",
    "question": "What should a new branch be called?",
    "today": "Branches are named after the issue.", "after": "Branches are named after the run.",
    "preview": "plaktoz/run-42",
    "options": [
        {"id": "run", "name": "Run name", "recommended": True, "see": "Branch names match the run.",
         "asks": "nothing", "pros": ["One name to search"], "cons": ["Old branches differ"]},
        {"id": "issue", "name": "Issue name", "see": "Branch names match the issue.",
         "asks": "nothing", "pros": ["No change"], "cons": ["Two names"]},
    ],
    "why": "One name is easier to find.",
}
PAGE = {"title": "T", "intro": "I", "target": "AGENTS.md", "storage_key": "k", "decisions": [CARD]}


def render(doc):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "p.json"
        src.write_text(json.dumps(doc), encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(RENDER), str(src)], capture_output=True, text=True)
        html = src.with_suffix(".html").read_text(encoding="utf-8") if r.returncode == 0 else ""
        return r, html


def with_card(**changes):
    doc = copy.deepcopy(PAGE)
    for k, v in changes.items():
        if v is None:
            doc["decisions"][0].pop(k)
        else:
            doc["decisions"][0][k] = v
    return doc


class CapTests(unittest.TestCase):
    def cards(self, n):
        doc = copy.deepcopy(PAGE)
        doc["decisions"] = [dict(copy.deepcopy(CARD), id=f"D{i + 1}") for i in range(n)]
        return doc

    def test_five_cards_render(self):
        r, _ = render(self.cards(5))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_sixth_card_is_refused_and_told_to_decide_it(self):
        r, _ = render(self.cards(6))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("most a page holds is 5", r.stderr)
        self.assertIn("docs/decisions.md", r.stderr)


class TriggerTests(unittest.TestCase):
    def test_a_card_with_a_stop_trigger_renders_and_shows_why_it_was_asked(self):
        r, html = render(PAGE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("reopens-decision", html)
        self.assertIn("Asked because", (RENDER.parent / "page.html").read_text(encoding="utf-8"))

    def test_a_card_with_no_trigger_is_refused_and_told_to_decide_it(self):
        r, _ = render(with_card(trigger=None))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("decide it at the recommendation", r.stderr)

    def test_a_trigger_outside_the_four_is_refused(self):
        r, _ = render(with_card(trigger="seems-important"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("seems-important", r.stderr)

    def test_a_trigger_with_no_detail_is_refused(self):
        r, _ = render(with_card(trigger_detail=None))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("trigger_detail", r.stderr)

    def test_an_old_shape_page_still_renders_with_a_warning(self):
        old = with_card(trigger=None, trigger_detail=None, question=None, today=None, after=None, preview=None)
        old["decisions"][0]["context"] = "Old context."
        for o in old["decisions"][0]["options"]:
            o.pop("see"); o.pop("asks")
        r, _ = render(old)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning", r.stderr)


if __name__ == "__main__":
    unittest.main()
