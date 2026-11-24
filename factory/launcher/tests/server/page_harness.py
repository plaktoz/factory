"""Drive the real dashboard page (module 15) in headless Chrome, with no new dependency.

The page under test is factory/dashboard/index.html, read as it ships. run_page copies it to a temp folder and adds one
script at the top of <head>. That script replaces fetch and the clipboard with recorders and serves the JSON the test
got from App.handle, so the page's own code runs on real server output. A timeline of steps runs on Chrome's virtual
clock (--virtual-time-budget): it changes what the stub serves, clicks the page's own buttons and takes snapshots. The
recorded result is written into <pre id="__out"> as JSON, and run_page reads it back.

Chrome gets its own profile folder, so the person's browser is never touched. The caller skips when Chrome is absent.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

from factory_launcher.server.settings import STATIC_DIR

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DASHBOARD = STATIC_DIR / "index.html"
BUDGET_MS = 12000

STUB = r"""
(function () {
  var responses = __RESPONSES__;
  var out = { fetches: [], clipboard: [], exec: [], snaps: {}, errors: [] };
  var clip = { mode: "ok" };
  window.__out = out;
  window.__clip = clip;
  window.addEventListener("error", function (e) { out.errors.push(String(e.message)); });
  var hanging = {};
  window.__set = function (path, body) { responses[path] = body; delete hanging[path]; };
  window.__hang = function (path) { hanging[path] = true; };
  window.fetch = function (path, opts) {
    var headers = (opts && opts.headers) || {};
    out.fetches.push({ path: path, method: (opts && opts.method) || "GET",
                       token: headers["X-Factory-Token"] || null, at: performance.now() });
    if (hanging[path]) {  // a server that never answers: the promise never settles, unless the page aborts it
      return new Promise(function (resolve, reject) {
        var signal = opts && opts.signal;
        if (signal) { signal.addEventListener("abort", function () { reject(new Error("aborted")); }); }
      });
    }
    var has = Object.prototype.hasOwnProperty.call(responses, path);
    var body = has ? responses[path] : JSON.stringify({ ok: false, code: "stub", message: "no stub for " + path });
    return Promise.resolve({ ok: has, status: has ? 200 : 404,
                             text: function () { return Promise.resolve(body); } });
  };
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
    writeText: function (text) {
      out.clipboard.push(text);
      return clip.mode === "refuse" ? Promise.reject(new Error("refused")) : Promise.resolve();
    } } });
  document.execCommand = function () {
    var areas = document.querySelectorAll("textarea");
    out.exec.push(areas.length ? areas[areas.length - 1].value : null);
    return true;
  };
  window.__snap = function (name, fn) {
    try { out.snaps[name] = fn(); } catch (e) { out.errors.push("snap " + name + ": " + e); }
  };
  window.__click = function (selector, text, index) {
    var items = Array.prototype.slice.call(document.querySelectorAll(selector))
      .filter(function (el) { return text == null || el.textContent.trim() === text; });
    if (!items[index || 0]) { out.errors.push("no element " + selector + " " + (text || "")); return; }
    items[index || 0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  };
  window.__flush = function () {
    var pre = document.getElementById("__out");
    if (!pre) { pre = document.createElement("pre"); pre.id = "__out"; document.body.appendChild(pre); }
    pre.textContent = JSON.stringify(out);
  };
})();
"""


def click(selector: str, text: str | None = None, index: int = 0) -> str:
    return f"__click({json.dumps(selector)}, {json.dumps(text)}, {index})"


def snap(name: str, fn_source: str) -> str:
    """fn_source is a JavaScript function expression; its return value is stored under `name`."""
    return f"__snap({json.dumps(name)}, {fn_source})"


def set_body(path: str, text: str) -> str:
    return f"__set({json.dumps(path)}, {json.dumps(text)})"


def hang(path: str) -> str:
    """From this step on, a request to `path` never answers, as a server that hangs would."""
    return f"__hang({json.dumps(path)})"


def set_clipboard(mode: str) -> str:
    return f"__clip.mode = {json.dumps(mode)}"


def run_page(tmp_path: Path, responses: dict[str, str], steps: list[tuple[int, str]], *, token: str,
             budget_ms: int = BUDGET_MS) -> dict:
    """Load the real page with the stub, run the timeline, and return the recorded result. `budget_ms` is Chrome's
    virtual clock: a test that waits past the default 12 s (the 10 s state timeout) passes a longer one."""
    timeline = [f"setTimeout(function () {{ {js} }}, {ms});" for ms, js in steps]
    timeline.append(f"setTimeout(function () {{ __flush(); }}, {budget_ms - 100});")
    script = STUB.replace("__RESPONSES__", json.dumps(responses)) + "\n" + "\n".join(timeline)
    script = script.replace("</", "<\\/")  # a response body can never close the script tag
    page_dir = tmp_path / "page"
    page_dir.mkdir()
    page = page_dir / "index.html"
    page.write_text(DASHBOARD.read_text().replace("</head>", f"<script>{script}</script></head>", 1))
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    url = page.as_uri() + "?token=" + token
    out = subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox", "--allow-file-access-from-files",
                          "--use-mock-keychain", "--password-store=basic", f"--user-data-dir={profile}",
                          f"--virtual-time-budget={budget_ms}", "--dump-dom", url],
                         capture_output=True, text=True, timeout=60)
    found = re.search(r'<pre id="__out">(.*?)</pre>', out.stdout, re.S)
    if found is None:
        raise AssertionError(f"the page wrote no result; chrome said: {out.stderr[-800:]}")
    return json.loads(html.unescape(found.group(1)))
