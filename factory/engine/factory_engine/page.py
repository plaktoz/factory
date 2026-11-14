"""The decision page (module 11): decisions/<stage>.<n>.html, filled from the packet with no LLM.

Packet text comes from an LLM, so every piece of it goes through html.escape and the page sets a strict content
security policy. The page is self-contained (inline CSS and script, no network call), so it opens from disk.
"""

from __future__ import annotations

import html
from pathlib import Path

from .atomic import write_text_atomic
from .decisions import Packet, page_path, read_decision
from .errors import FactoryError

# Without submit_url the page may not connect anywhere. With it, only the page's own origin.
_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'none'; form-action 'none'"
_CSP_SUBMIT = _CSP.replace("default-src 'none';", "default-src 'none'; connect-src 'self';")

_STYLE = """
body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1b1f24;background:#fff}
h1{font-size:1.4rem}h2{font-size:1.15rem;margin-top:2rem}section.decision{border-top:1px solid #d0d7de;padding-top:.5rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:.75rem}
label.card{display:block;border:1px solid #d0d7de;border-radius:6px;padding:.75rem;cursor:pointer}
label.card:has(input:checked){border-color:#0969da;background:#ddf4ff}
.badge{background:#1a7f37;color:#fff;border-radius:1rem;padding:0 .5rem;font-size:.75rem;margin-left:.4rem}
.flow{display:flex;flex-wrap:wrap;gap:.25rem;margin:.4rem 0}.step{border:1px solid #d0d7de;border-radius:4px;padding:0 .4rem;font-size:.8rem}
.pros li::marker{content:"+ "}.cons li::marker{content:"- "}
table{border-collapse:collapse}td,th{border:1px solid #d0d7de;padding:.25rem .5rem;text-align:left}
textarea{width:100%;box-sizing:border-box}pre{background:#f6f8fa;padding:.75rem;overflow:auto;white-space:pre-wrap;word-break:break-all}
button{font:inherit;padding:.3rem .8rem}.state{color:#57606a}.err{color:#cf222e}
@media (prefers-color-scheme:dark){body{background:#0d1117;color:#e6edf3}label.card,td,th,.step,section.decision{border-color:#30363d}
label.card:has(input:checked){background:#0c2d6b}pre{background:#161b22}.state{color:#8b949e}}
"""

_SCRIPT = r"""
(function () {
  var root = document.getElementById("factory-decision");
  var cli = root.getAttribute("data-cli"), run = root.getAttribute("data-run"), sha = root.getAttribute("data-sha");
  var submitUrl = root.getAttribute("data-submit-url");
  function quote(s) {
    return /^[A-Za-z0-9_@%+=:,.\/-]+$/.test(s) ? s : "'" + s.replace(/'/g, "'\\''") + "'";
  }
  function answer() {
    var choices = {}, questions = {}, ids = [];
    document.querySelectorAll("section.decision").forEach(function (sec) {
      var id = sec.getAttribute("data-id");
      ids.push(id);
      var q = sec.querySelector("textarea.ask").value.trim();
      var picked = sec.querySelector("input[type=radio]:checked");
      if (q) { questions[id] = q; } else if (picked) { choices[id] = picked.value; }
    });
    return { ids: ids, choices: choices, questions: questions, notes: document.getElementById("notes").value };
  }
  function command(a) {
    var parts = [cli, "decide", run, "--packet", sha];
    a.ids.forEach(function (id) { if (a.choices[id]) { parts.push(id + "=" + a.choices[id]); } });
    if (a.notes.trim()) { parts.push("--notes", quote(a.notes)); }
    a.ids.forEach(function (id) { if (a.questions[id]) { parts.push("--question", quote(id + "=" + a.questions[id])); } });
    return parts.join(" ");
  }
  function refresh() {
    var a = answer();
    document.getElementById("cmd").textContent = command(a);
    var missing = a.ids.filter(function (id) { return !a.choices[id] && !a.questions[id]; });
    document.getElementById("missing").textContent = missing.length ? "Still to answer: " + missing.join(", ") : "";
  }
  document.addEventListener("input", refresh);
  document.addEventListener("change", refresh);
  document.getElementById("copy").addEventListener("click", function () {
    var text = document.getElementById("cmd").textContent;
    var done = function () { document.getElementById("copied").textContent = "Copied"; };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(text); done(); });
    } else { fallback(text); done(); }
  });
  function fallback(text) {
    var t = document.createElement("textarea");
    t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand("copy"); } catch (e) {}
    document.body.removeChild(t);
  }
  var submit = document.getElementById("submit");
  if (submit && submitUrl) {
    submit.hidden = false;
    submit.addEventListener("click", function () {
      var a = answer();
      var headers = { "Content-Type": "application/json" };
      if (window.FACTORY_TOKEN) { headers["X-Factory-Token"] = window.FACTORY_TOKEN; }
      fetch(submitUrl, { method: "POST", headers: headers, body: JSON.stringify({
        run: run, packet: sha, choices: a.choices, questions: a.questions, notes: a.notes, channel: "dashboard" }) })
        .then(function (r) { return r.text().then(function (t) { document.getElementById("submitted").textContent = r.ok ? "Sent" : t; }); })
        .catch(function (e) { document.getElementById("submitted").textContent = String(e); });
    });
  }
  refresh();
})();
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _list(items: list[str], cls: str) -> str:
    if not items:
        return ""
    return f'<ul class="{cls}">' + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>"


def _flow(steps: list[str]) -> str:
    out = []
    for s in steps:
        who, _, what = s.partition(":")
        out.append(f'<span class="step">{_e(who)}: {_e(what)}</span>' if what else f'<span class="step">{_e(s)}</span>')
    return '<div class="flow">' + " &rarr; ".join(out) + "</div>"


def _compare(d: dict) -> str:
    c = d["compare"]
    names = {o["id"]: o["name"] for o in d["options"]}
    head = f"<tr><th></th><th>{_e(names.get(c['a'], c['a']))}</th><th>{_e(names.get(c['b'], c['b']))}</th></tr>"
    rows = "".join("<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>" for row in c["rows"])
    return (f"<h3>Often confused</h3><table>{head}{rows}</table>"
            f"<p>Choose {_e(names.get(c['a'], c['a']))} if: {_e(c['choose_a_if'])}</p>"
            f"<p>Choose {_e(names.get(c['b'], c['b']))} if: {_e(c['choose_b_if'])}</p>")


def _decision(d: dict, picked: str | None) -> str:
    ctx = d["context"]
    terms = "".join(f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in ctx["terms"].items())
    cards = []
    for o in d["options"]:
        rec = d["recommend"] == o["id"]
        on = picked == o["id"] or (picked is None and rec)
        cards.append(
            f'<label class="card"><input type="radio" name="{_e(d["id"])}" value="{_e(o["id"])}"{" checked" if on else ""}>'
            f' <strong>{_e(o["name"])}</strong>{"<span class=badge>Recommended</span>" if rec else ""}'
            f'{_flow(o["flow"])}{_list(o["pros"], "pros")}{_list(o["cons"], "cons")}</label>')
    return (
        f'<section class="decision" data-id="{_e(d["id"])}"><h2>{_e(d["id"])}. {_e(d["title"])}</h2>'
        f'<p><strong>{_e(d["question"])}</strong></p>'
        f'<p>{_e(ctx["what"])}</p><p><em>For example:</em> {_e(ctx["example"])}</p>'
        f'{"<dl>" + terms + "</dl>" if terms else ""}'
        f'{_compare(d)}<h3>Options</h3><div class="cards">{"".join(cards)}</div>'
        f'<p>Recommended: {_e(d["recommend"])}. {_e(d["why"])}</p>'
        f'<label>Not sure? Ask a question instead of choosing:<textarea class="ask" rows="2"></textarea></label></section>')


def render_page(run_dir: Path, stage: str, visit: int, *, cli: str = "factory", submit_url: str | None = None) -> Path:
    """Write decisions/<stage>.<n>.html from the packet. A failed write leaves the YAML file untouched."""
    doc = read_decision(run_dir, stage, visit)
    packet: Packet = doc["packet"]
    dec = doc["decision"]
    sections = "".join(_decision(d, dec["choices"].get(d["id"])) for d in packet["decisions"])
    status = f"Answered: {_e(dec['status'])}" if dec["status"] != "pending" else "Waiting for your answer"
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{_e(_CSP_SUBMIT if submit_url else _CSP)}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(run_dir.name)}: {_e(stage)} decision</title><style>{_STYLE}</style></head>
<body><main id="factory-decision" data-cli="{_e(cli)}" data-run="{_e(run_dir.name)}" data-sha="{_e(packet['sha'])}"
 data-submit-url="{_e(submit_url or '')}">
<h1>{_e(run_dir.name)}: {_e(stage)}</h1><p class="state">Packet {_e(packet['sha'])}. {status}.</p>
{sections}
<section><h2>Review and submit</h2>
<label>Notes<textarea id="notes" rows="3">{_e(dec['notes'])}</textarea></label>
<p>Run this command:</p><pre id="cmd"></pre>
<p><button id="copy" type="button">Copy</button> <span id="copied" class="state"></span>
<button id="submit" type="button" hidden>Submit</button> <span id="submitted" class="state"></span></p>
<p id="missing" class="err"></p>
<p class="state">If the packet changes, the command is refused. Reopen this page for the current packet.</p>
</section></main>
<script>{_SCRIPT}</script></body></html>
"""
    path = page_path(run_dir, stage, visit)
    try:
        write_text_atomic(path, body)
    except OSError as e:
        raise FactoryError("decision.render_failed", f"{path}: {e}") from e
    return path

