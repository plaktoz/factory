"""Module 11 acceptance criteria, page half: picker parts, escaping, offline, and the copied command."""

import html as htmllib
import re
import subprocess
from pathlib import Path

import pytest

from factory_engine import decisions as D
from factory_engine import page
from factory_engine.errors import FactoryError

from decisions_helpers import architect_packet, decision, option

HOSTILE = '<img src=x onerror="alert(1)"><script>steal()</script> & "quotes"'
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def hostile_packet():
    return architect_packet(
        decision("D1", title=HOSTILE, question=HOSTILE,
                 context={"what": HOSTILE, "example": HOSTILE, "terms": {"SPA": HOSTILE}},
                 options=[option("opt-a", HOSTILE, pros=[HOSTILE], cons=[HOSTILE], flow=[f"human:{HOSTILE}"]),
                          option("opt-b", "Server pages")]),
        decision("D2", title="Datastore", question="Which datastore?"))


def request_page(run, packet=None):
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=packet or architect_packet())
    return (run.run_dir / "decisions" / "architecture.1.html").read_text()


def test_the_page_renders_every_picker_part(run):
    text = request_page(run)
    for part in ["Often confused", "Options", "Recommended", "Not sure?", "Review and submit", "Copy",
                 "For example:", "Choose React if:", 'class="flow"', 'class="pros"', 'class="cons"']:
        assert part in text, part
    assert 'type="radio"' in text and 'textarea class="ask"' in text and 'id="notes"' in text


def test_the_recommended_option_is_preselected(run):
    text = request_page(run)
    assert 'value="opt-a" checked' in text
    assert 'value="opt-b" checked' not in text


def test_all_packet_text_is_escaped(run):
    text = request_page(run, hostile_packet())
    assert "<script>steal()</script>" not in text and "<img src=x" not in text
    assert "&lt;script&gt;steal()&lt;/script&gt;" in text
    assert "&quot;quotes&quot;" in text


def test_the_page_sets_a_strict_content_security_policy_without_a_submit_url(run):
    text = request_page(run)
    policy = htmllib.unescape(re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', text).group(1))
    assert "default-src 'none'" in policy and "form-action 'none'" in policy
    assert "connect-src" not in policy


def test_the_page_loads_nothing_from_the_network(run):
    text = request_page(run)
    assert not re.search(r'(src|href)="https?:', text)
    assert "<link" not in text and "@import" not in text
    assert "https://" not in text and "http://" not in text


def test_the_page_is_regenerated_when_missing_and_kept_when_current(run):
    request_page(run)
    p = run.run_dir / "decisions" / "architecture.1.html"
    p.unlink()
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=architect_packet())
    assert p.is_file()


def test_the_page_follows_a_new_packet(run):
    request_page(run)
    new = architect_packet(decision(), decision("D2", title="Datastore"))
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=new)
    sha = D.read_decision(run.run_dir, "architecture", 1)["packet"]["sha"]
    assert f'data-sha="{sha}"' in (run.run_dir / "decisions" / "architecture.1.html").read_text()


def test_a_failed_render_leaves_the_yaml_usable_and_keeps_the_error_on_the_event(run, monkeypatch):
    def refuse(run_dir, stage, visit, **kw):
        raise FactoryError("decision.render_failed", "disk full")
    monkeypatch.setattr(page, "render_page", refuse)
    sha = D.request(run.run_dir, "architecture", 1, kind="decision", packet=architect_packet())
    assert D.read_decision(run.run_dir, "architecture", 1)["packet"]["sha"] == sha
    from factory_engine import state
    requested = [e for e in state.read_events(run.run_dir) if e.type == "decision_requested"]
    assert requested[0].data["page_error"] == "disk full"


def test_render_page_raises_a_factory_error_when_the_write_fails(run, monkeypatch):
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=architect_packet())

    def refuse(path, data):
        raise OSError("read-only")
    monkeypatch.setattr(page, "write_text_atomic", refuse)
    with pytest.raises(FactoryError) as e:
        page.render_page(run.run_dir, "architecture", 1)
    assert e.value.code == "decision.render_failed"


def _chrome_dom(page_path: Path) -> str:
    """Load the page from disk in headless Chrome, with scripts on, and return the DOM after they ran."""
    out = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox", "--allow-file-access-from-files",
                          "--virtual-time-budget=2000", "--dump-dom", page_path.as_uri()],
                         capture_output=True, text=True, timeout=60)
    return out.stdout


@pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome is not installed")
def test_the_page_opens_from_disk_and_its_command_matches_the_picks(run, tmp_path):
    """The script runs in a real browser from a file on disk. The page is saved with a different pick and a
    note that holds a quote, and the command it prints must name exactly those picks, shell-quoted."""
    D.request(run.run_dir, "architecture", 1, kind="decision", packet=architect_packet())
    sha = D.read_decision(run.run_dir, "architecture", 1)["packet"]["sha"]
    text = (run.run_dir / "decisions" / "architecture.1.html").read_text()
    # D1 defaults to opt-a. Move the pick to opt-b, and write the note the reviewer typed.
    text = text.replace('name="D1" value="opt-a" checked', 'name="D1" value="opt-a"', 1)
    text = text.replace('name="D1" value="opt-b"', 'name="D1" value="opt-b" checked', 1)
    text = text.replace('id="notes" rows="3">', 'id="notes" rows="3">Keep it simple, the team\'s call', 1)
    copy = tmp_path / "architecture.1.html"
    copy.write_text(text)
    dom = _chrome_dom(copy)
    cmd = htmllib.unescape(re.search(r'<pre id="cmd">(.*?)</pre>', dom, re.S).group(1))
    assert cmd == (f"factory decide new-color-q1w2e --packet {sha} D1=opt-b D2=opt-a "
                   f"--notes 'Keep it simple, the team'\\''s call'")
