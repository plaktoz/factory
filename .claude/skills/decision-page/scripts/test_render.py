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


def render_args(doc, *flags):
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "p.json"
        src.write_text(json.dumps(doc), encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(RENDER), *flags, str(src)], capture_output=True, text=True)
        html = src.with_suffix(".html").read_text(encoding="utf-8") if src.with_suffix(".html").exists() else ""
        return r, html


class CapTests(unittest.TestCase):
    def cards(self, n):
        doc = copy.deepcopy(PAGE)
        doc["decisions"] = [dict(copy.deepcopy(CARD), id=f"D{i + 1}") for i in range(n)]
        return doc

    def test_five_cards_render_with_no_warning(self):
        r, _ = render(self.cards(5))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("warning", r.stderr)

    def test_a_sixth_card_renders_and_warns(self):
        r, html = render(self.cards(6))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning", r.stderr)
        self.assertIn("at most 5", r.stderr)
        self.assertIn("D6", html)


class GuidanceWarnsButRendersTests(unittest.TestCase):
    """What SKILL.md asks for and the page does not need: a warning, and the page is still written."""

    def assertWarns(self, doc, text):
        r, html = render(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("warning", r.stderr)
        self.assertIn(text, r.stderr)
        self.assertNotEqual(html, "")
        self.assertNotIn("undefined", html)

    def test_a_card_with_no_trigger(self):
        self.assertWarns(with_card(trigger=None), "trigger")

    def test_a_trigger_outside_the_four(self):
        self.assertWarns(with_card(trigger="seems-important"), "seems-important")

    def test_a_trigger_with_no_detail(self):
        self.assertWarns(with_card(trigger_detail=None), "trigger_detail")

    def test_a_question_that_is_not_a_question(self):
        self.assertWarns(with_card(question="Pick a name."), "question")

    def test_a_builder_word_in_see(self):
        doc = with_card()
        doc["decisions"][0]["options"][0]["see"] = "A new function names the branch."
        self.assertWarns(doc, "function")

    def test_an_unexplained_internal_id(self):
        self.assertWarns(with_card(today="Per D9 the branch is the issue name."), "D9")

    def test_one_option_only(self):
        doc = with_card()
        doc["decisions"][0]["options"].pop()
        self.assertWarns(doc, "1 options")

    def test_an_option_with_no_cons(self):
        doc = with_card()
        doc["decisions"][0]["options"][0]["cons"] = []
        self.assertWarns(doc, "cons")

    def test_an_option_with_no_see_or_asks(self):
        doc = with_card()
        for k in ("see", "asks"): doc["decisions"][0]["options"][0].pop(k, None)
        self.assertWarns(doc, "'see' is missing")

    def test_a_card_with_only_a_title_and_options_renders(self):
        doc = {"decisions": [{"id": "D1", "options": [
            {"id": "a", "name": "A", "recommended": True}, {"id": "b", "name": "B"}]}]}
        r, html = render(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("undefined", html)

    def test_two_recommended_options_warn_and_still_render(self):
        doc = with_card()
        doc["decisions"][0]["options"][1]["recommended"] = True
        self.assertWarns(doc, "recommended")

    def test_an_old_shape_page_still_renders_with_a_warning(self):
        old = with_card(trigger=None, trigger_detail=None, question=None, today=None, after=None, preview=None)
        old["decisions"][0]["context"] = "Old context."
        for o in old["decisions"][0]["options"]:
            o.pop("see"); o.pop("asks")
        self.assertWarns(old, "old shape")

    def test_a_card_that_meets_the_house_style_prints_no_warning(self):
        r, html = render(PAGE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("warning", r.stderr)
        self.assertIn("reopens-decision", html)
        self.assertIn("Asked because", (RENDER.parent / "page.html").read_text(encoding="utf-8"))


class StrictTests(unittest.TestCase):
    def test_strict_fails_on_a_warning_but_still_writes_the_page(self):
        r, html = render_args(with_card(trigger=None), "--strict")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotEqual(html, "")

    def test_strict_passes_a_clean_page(self):
        r, _ = render_args(PAGE, "--strict")
        self.assertEqual(r.returncode, 0, r.stderr)


class RealErrorTests(unittest.TestCase):
    """What would make the page or its prompt wrong stays an error."""

    def assertRefused(self, doc, text):
        r, _ = render(doc)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(text, r.stderr)

    def test_no_decisions(self):
        self.assertRefused({"decisions": []}, "decisions")

    def test_a_decision_with_no_id(self):
        self.assertRefused(with_card(id=None), "no 'id'")

    def test_a_duplicate_decision_id(self):
        doc = copy.deepcopy(PAGE)
        doc["decisions"].append(copy.deepcopy(CARD))
        self.assertRefused(doc, "duplicate decision id")

    def test_a_duplicate_option_id(self):
        doc = with_card()
        doc["decisions"][0]["options"][1]["id"] = "run"
        self.assertRefused(doc, "duplicate or reserved")

    def test_the_reserved_option_id(self):
        doc = with_card()
        doc["decisions"][0]["options"][1]["id"] = "unsure"
        self.assertRefused(doc, "duplicate or reserved")

    def test_no_recommended_option(self):
        doc = with_card()
        doc["decisions"][0]["options"][0]["recommended"] = False
        self.assertRefused(doc, "recommended")

    def test_a_file_that_is_not_json(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "p.json"
            src.write_text("{not json", encoding="utf-8")
            r = subprocess.run([sys.executable, "-I", str(RENDER), str(src)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot read", r.stderr)


if __name__ == "__main__":
    unittest.main()
