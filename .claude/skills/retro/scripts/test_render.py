"""Tests for render.py. Run: python3 -I -m unittest .claude/skills/retro/scripts/test_render.py"""
import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

RENDER = Path(__file__).with_name("render.py")

FACTS = {
    "active_s": 360000,
    "buckets": {"think_reply": 140000, "wait_machine": 72000},
    "waiting": {"reply": {"n": 283, "total_s": 67300, "by_kind": {"status": {"n": 144, "s": 41320}}},
                "question": {"n": 43, "total_s": 49871, "long_n": 3, "long_s": 44676, "capped_s": 10595, "median_s": 51}},
    "decisions": {"answered": 48, "followed": 42, "follow_rate": 88, "themes": {}, "repeated_headers": [], "per_day": {}},
    "commands": {}, "gh_repeat_reads": {"n": 132, "s": 990.1},
}
SIGNALS = [{"id": "stops-without-asking", "n": 144, "s": 41320}]

FINDING = {
    "id": "F1", "signal": "stops-without-asking", "title": "The agent ends turns with a status update",
    "category": "supervision", "impact": "high",
    "trigger": "changes-scope", "trigger_detail": "Changes when a session may stop, which AGENTS.md sets.",
    "evidence": [{"fact": "waiting.reply.by_kind.status.n", "label": "gaps after a status update"}],
    "today": "144 of 283 replies follow a status update that asked nothing.",
    "after": "A session stops only for a question or a delivery.",
    "options": [
        {"id": "rule", "name": "Add a stop rule", "recommended": True,
         "see": "A session keeps working after a status update.", "asks": "nothing",
         "pros": ["Cuts idle turns"], "cons": ["A session may run on past a real problem"]},
        {"id": "leave", "name": "Leave it", "see": "No change.", "asks": "nothing",
         "pros": ["No rule to maintain"], "cons": ["The gaps stay"]},
    ],
    "why": "A status update gives the owner nothing to decide.",
}
REPORT = {"title": "Retro", "intro": "One week of sessions.", "period": "2026-11-14 to 2026-11-22",
          "storage_key": "retro-1", "limits": ["Reply kinds are read by keyword."], "findings": [FINDING]}


def render(report, facts=FACTS, signals=SIGNALS):
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        (base / "facts.json").write_text(json.dumps({"facts": facts, "signals": signals}), encoding="utf-8")
        (base / "r.json").write_text(json.dumps(report), encoding="utf-8")
        r = subprocess.run([sys.executable, "-I", str(RENDER), str(base / "r.json"), str(base / "facts.json")],
                           capture_output=True, text=True)
        md = (base / "r.md").read_text(encoding="utf-8") if (base / "r.md").exists() else ""
        html = (base / "r.html").read_text(encoding="utf-8") if (base / "r.html").exists() else ""
        return r, md, html


def with_finding(**changes):
    doc = copy.deepcopy(REPORT)
    for k, v in changes.items():
        if v is None:
            doc["findings"][0].pop(k)
        else:
            doc["findings"][0][k] = v
    return doc


class Render(unittest.TestCase):
    def test_a_valid_report_writes_markdown_and_html_beside_the_json(self):
        r, md, html = render(REPORT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("The agent ends turns with a status update", md)
        self.assertIn("Add a stop rule", md)
        self.assertIn("144", md)
        self.assertIn("<!doctype html>", html.lower())

    def test_each_evidence_fact_is_looked_up_and_its_value_is_printed(self):
        r, md, html = render(REPORT)
        self.assertIn("gaps after a status update", md)
        self.assertIn("144", md)

    def test_an_evidence_path_that_is_not_in_the_facts_is_refused(self):
        bad = with_finding(evidence=[{"fact": "waiting.reply.by_kind.invented.n", "label": "x"}])
        r, _, _ = render(bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invented", r.stderr)

    def test_a_finding_must_name_a_signal_that_fired_or_say_it_is_judgment(self):
        bad = with_finding(signal="not-a-signal")
        r, _, _ = render(bad)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("signal", r.stderr)
        ok = with_finding(signal="judgment")
        r, _, _ = render(ok)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_exactly_one_recommended_option_and_two_to_four_options(self):
        doc = with_finding()
        doc["findings"][0]["options"][1]["recommended"] = True
        r, _, _ = render(doc)
        self.assertNotEqual(r.returncode, 0)
        doc = with_finding()
        doc["findings"][0]["options"] = doc["findings"][0]["options"][:1]
        r, _, _ = render(doc)
        self.assertNotEqual(r.returncode, 0)

    def test_every_option_lists_a_pro_and_a_con(self):
        doc = with_finding()
        doc["findings"][0]["options"][0]["cons"] = []
        r, _, _ = render(doc)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cons", r.stderr)

    def test_the_trigger_must_be_one_of_the_stop_triggers_or_routine(self):
        r, _, _ = render(with_finding(trigger="whenever"))
        self.assertNotEqual(r.returncode, 0)
        r, _, _ = render(with_finding(trigger="routine", trigger_detail="A reversible default."))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_limits_are_required_so_a_report_cannot_hide_what_it_could_not_see(self):
        doc = copy.deepcopy(REPORT)
        doc["limits"] = []
        r, _, _ = render(doc)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("limits", r.stderr)

    def test_the_html_keeps_text_from_closing_the_script_tag(self):
        doc = with_finding(why="</script><b>x</b>")
        r, _, html = render(doc)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("</script><b>", html)

    def test_the_markdown_ends_with_a_prompt_that_names_every_default_choice(self):
        r, md, _ = render(REPORT)
        tail = md.split("## Prompt")[-1]
        self.assertIn("F1", tail)
        self.assertIn("Add a stop rule [rule]", tail)
        self.assertIn("(recommended)", tail)

    def test_an_unreadable_facts_file_fails_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "r.json").write_text(json.dumps(REPORT), encoding="utf-8")
            r = subprocess.run([sys.executable, "-I", str(RENDER), str(Path(d) / "r.json"), str(Path(d) / "none.json")],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("facts", r.stderr)


if __name__ == "__main__":
    unittest.main()
