"""A profile step may name the registry hosts it reaches under srt (owner decision, 2026-11-25, `profile-steps-whitelist-their-registries`).

The profile key is `variants.<variant>.network.<step>: [host, ...]`. Each host is a plain hostname. The command adapter puts
a step's hosts into `sandbox.network.allowedDomains` for that one task, and no other command gets them. Module 9 and
module 17A say so; these tests hold the rules in code.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from factory_engine import toolchains
from factory_engine.adapters.worker import sandbox
from factory_engine.adapters.worker.base import TaskContext
from factory_engine.adapters.worker.base import HarnessConfig
from factory_engine.adapters.worker.command import CommandAdapter
from factory_engine.errors import FactoryError
from factory_engine.types import HelperPolicy, TaskSpec

from test_toolchains import CFG, fixture


def harness(command: str) -> HarnessConfig:
    return HarnessConfig(command=command, model=None, args=[], env={})

KIT = Path(__file__).resolve().parents[3] / "languages"


@pytest.fixture
def worktree(tmp_path) -> Path:
    wt = tmp_path / "wt"
    wt.mkdir()
    return wt


@pytest.fixture
def task_dir(tmp_path) -> Path:
    d = tmp_path / "run" / "tasks" / "backend" / "work"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def factory_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("FACTORY_HOME", str(home))
    return home


def _profile(worktree: Path, body: str) -> None:
    """A repo profile in the worktree's override folder, which replaces the shipped java profile for this test."""
    d = worktree / ".factory" / "config" / "languages"
    d.mkdir(parents=True, exist_ok=True)
    (d / "java.yaml").write_text(body)


JAVA_WITH = """name: java
detect: {any_file: [pom.xml]}
files: ["**/*.java"]
variants:
  maven:
    when: {file: pom.xml}
    test: [mvn, -q, test]
    network: {test: %s}
"""


# ---- the Maven test step: srt's proxy reaches Maven's resolver through settings.xml (measured 2026-11-25) ------------

def _maven_test_argv():
    import yaml
    return yaml.safe_load((KIT / "java.yaml").read_text())["variants"]["maven"]["test"]


def _stub_mvn(bindir: Path, record: Path) -> None:
    """A stand-in `mvn` that records its argv and the proxy settings file it was given, and writes no report."""
    bindir.mkdir(exist_ok=True)
    p = bindir / "mvn"
    p.write_text("#!/bin/sh\n"
                 f"echo \"$@\" > {record}\n"
                 "prev=\"\"\n"
                 "for a in \"$@\"; do\n"
                 f"  if [ \"$prev\" = -s ]; then cp \"$a\" {record}.settings; fi\n"
                 "  prev=\"$a\"\n"
                 "done\n"
                 "exit 0\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_the_maven_test_step_hands_mvn_a_proxy_settings_file_when_srt_sets_one(tmp_path, monkeypatch, task_dir):
    """Maven's resolver ignores the JVM proxy properties that srt's agent sets, so the step gives mvn a settings file with
    srt's proxy (from HTTPS_PROXY). Without this the allowed download still fails (measured 2026-11-25)."""
    bins = tmp_path / "bin"
    record = tmp_path / "mvn-argv.txt"
    _stub_mvn(bins, record)
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:p%40ss@localhost:58359")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pom.xml").write_text("<project/>")
    subprocess.run(_maven_test_argv(), cwd=proj, env={**os.environ, "FACTORY_TASK_DIR": str(task_dir)},
                   capture_output=True, text=True, timeout=60)
    argv = record.read_text().split()
    assert "-s" in argv and "test" in argv
    settings = Path(str(record) + ".settings").read_text()
    assert "<host>localhost</host>" in settings and "<port>58359</port>" in settings
    assert "<username>user</username>" in settings and "<password>p@ss</password>" in settings
    assert not (task_dir / "maven-proxy-settings.xml").exists(), "the file holds the proxy password and must be removed"


def test_the_proxy_settings_file_is_removed_even_when_mvn_fails(tmp_path, monkeypatch, task_dir):
    """A failing mvn still leaves no password file in the task folder (the finally in the step)."""
    bins = tmp_path / "bin"
    record = tmp_path / "mvn-argv.txt"
    _stub_mvn(bins, record)
    (bins / "mvn").write_text((bins / "mvn").read_text().replace("exit 0", "exit 1"))
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pw@localhost:58359")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pom.xml").write_text("<project/>")
    r = subprocess.run(_maven_test_argv(), cwd=proj, env={**os.environ, "FACTORY_TASK_DIR": str(task_dir)},
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert not (task_dir / "maven-proxy-settings.xml").exists()


def test_the_maven_test_step_without_a_proxy_runs_mvn_with_no_settings_file(tmp_path, monkeypatch, task_dir):
    """Outside srt there is no HTTPS_PROXY, so the step adds no -s and mvn runs as it always did."""
    bins = tmp_path / "bin"
    record = tmp_path / "mvn-argv.txt"
    _stub_mvn(bins, record)
    monkeypatch.setenv("PATH", f"{bins}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pom.xml").write_text("<project/>")
    subprocess.run(_maven_test_argv(), cwd=proj, env={**os.environ, "FACTORY_TASK_DIR": str(task_dir)},
                   capture_output=True, text=True, timeout=60)
    assert "-s" not in record.read_text().split()
    assert not Path(str(record) + ".settings").exists()


# ---- the loader: the shipped profile and the refusals --------------------------------------------------------------

def test_the_shipped_java_maven_test_step_allows_only_the_maven_central_host():
    import yaml
    doc = yaml.safe_load((KIT / "java.yaml").read_text())
    assert doc["variants"]["maven"]["network"] == {"test": ["repo.maven.apache.org"]}


def test_no_shipped_profile_allows_a_host_for_any_step_but_java_test():
    import yaml
    allowed = {}
    for p in sorted(KIT.glob("*.yaml")):
        for vname, v in (yaml.safe_load(p.read_text()).get("variants") or {}).items():
            for step, hosts in (v.get("network") or {}).items():
                allowed[(p.stem, vname, step)] = hosts
    assert allowed == {("java", "maven", "test"): ["repo.maven.apache.org"]}


@pytest.mark.parametrize("hosts", [
    '["repo.maven.apache.org/maven2"]',      # a path
    '["https://repo.maven.apache.org"]',     # a scheme
    '["*.apache.org"]',                      # a wildcard
    '["*"]',                                 # everything
    '["10.0.0.5"]',                          # an IP address
    '["repo.maven.apache.org:443"]',         # a port
    '[""]',                                  # empty
    '[42]',                                  # not a string
    '"repo.maven.apache.org"',               # not a list
])
def test_a_network_host_that_is_not_a_plain_hostname_is_refused_at_load(tmp_path, hosts):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    _profile(w, JAVA_WITH % hosts)
    with pytest.raises(FactoryError) as e:
        toolchains.detect(w, CFG)
    assert e.value.code == "config.invalid"


def test_a_network_key_for_an_unknown_step_is_refused_at_load(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>"})
    _profile(w, JAVA_WITH.replace("network: {test: %s}", "network: {deploy: [repo.maven.apache.org]}"))
    with pytest.raises(FactoryError) as e:
        toolchains.detect(w, CFG)
    assert e.value.code == "config.invalid"


def test_a_format_or_lint_step_host_reaches_its_own_srt_settings(tmp_path, monkeypatch):
    """A network key on a formatter or lint step is honoured for that step, the same rule as the test step. Each step's
    srt settings carry only that step's hosts (run_step passes tc.network[step] to _sandboxed)."""
    import shutil
    from factory_engine.toolchains import _sandboxed
    monkeypatch.setenv("FACTORY_HOME", str(tmp_path / "home"))
    wt = tmp_path / "wt"
    wt.mkdir()
    for domains, expected in ((["pypi.org"], ["pypi.org"]), (None, [])):
        wrapped, folder = _sandboxed(wt, ["ruff", "check"], domains)
        try:
            settings = json.loads(Path(wrapped[wrapped.index("-s") + 1]).read_text())
            assert settings["network"]["allowedDomains"] == expected
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def test_a_profile_without_a_network_key_gets_no_hosts(tmp_path):
    w = fixture(tmp_path, {"pyproject.toml": "[project]\n"})
    assert all(tc.network == {} for tc in toolchains.detect(w, CFG))


# ---- the plumbing: a step's hosts reach its test task and nothing else ----------------------------------------------

def test_the_java_test_task_carries_the_maven_host_and_the_other_java_steps_do_not(tmp_path):
    w = fixture(tmp_path, {"pom.xml": "<project/>", "src/A.java": "class A{}\n"})
    [task] = toolchains.language_tasks(w, CFG, "test", ["src/A.java"])
    assert task.network_domains == ["repo.maven.apache.org"]
    tc = toolchains.detect(w, CFG)[0]
    assert tc.network.get("build", []) == [] and tc.network.get("lint", []) == []


def test_a_typescript_test_task_gets_no_hosts(tmp_path):
    w = fixture(tmp_path, {"package.json": "{}", "web/app.ts": "export {};\n"})
    [task] = toolchains.language_tasks(w, CFG, "test", ["web/app.ts"])
    assert task.network_domains == []


def test_hosts_survive_the_frozen_language_list(tmp_path):
    """The verify stage freezes its test tasks in languages.json, so a rebuilt task must keep its hosts."""
    from factory_engine.engine import _spec_from_doc, _spec_to_doc
    spec = TaskSpec(id="test-java", skill=None, cmd=["mvn", "-q", "test"], run=None, scope=[], deny=[], needs=[],
                    helpers=HelperPolicy("off", 0, [], None), out=None, timeout_minutes=30, retries=0, model=None,
                    when=None, network_domains=["repo.maven.apache.org"])
    doc = _spec_to_doc(spec)
    assert _spec_from_doc(doc).network_domains == ["repo.maven.apache.org"]


def test_a_frozen_list_written_before_this_key_existed_reads_with_no_hosts():
    """languages.json from a run that started before the key existed has no network field: it reads as no hosts."""
    from factory_engine.engine import _spec_from_doc
    doc = {"id": "test-java", "cmd": ["mvn"], "scope": [], "deny": [], "needs": [],
           "helpers": {"mode": "off", "max": 0, "split_hints": [], "timeout_minutes": None},
           "out": "test.junit.xml", "timeout_minutes": 30, "retries": 0, "max_interruptions": 3}
    assert _spec_from_doc(doc).network_domains == []


# ---- the srt settings: one task's allowance, not the others ---------------------------------------------------------

def _ctx(worktree, task_dir, cmd, domains):
    return TaskContext(run_id="run-1", task_id="test-java", stage="verify", attempt=1, skill=None, request=None,
                       worktree=worktree, task_dir=task_dir, scope=[], deny=[], helpers=None, feedback=[], notes=[],
                       progress=None, output_schema=None, model=None, mcp=[], practices=[], cmd=list(cmd),
                       artifact_name="test.junit.xml", network_domains=list(domains))


def _settings_for(adapter, ctx, folder):
    return json.loads(adapter._settings(ctx, folder).read_text())


def test_the_java_test_task_settings_allow_the_maven_host(tmp_path, worktree, task_dir):
    folder = tmp_path / "attempt"
    folder.mkdir()
    s = _settings_for(CommandAdapter({}), _ctx(worktree, task_dir, ["mvn", "-q", "test"], ["repo.maven.apache.org"]), folder)
    assert s["network"]["allowedDomains"] == ["repo.maven.apache.org"]


def test_a_task_with_no_hosts_gets_an_empty_allowance(tmp_path, worktree, task_dir):
    folder = tmp_path / "attempt"
    folder.mkdir()
    s = _settings_for(CommandAdapter({}), _ctx(worktree, task_dir, ["npm", "test"], []), folder)
    assert s["network"]["allowedDomains"] == []


def test_a_host_on_one_task_is_not_passed_to_another_task(tmp_path, worktree, task_dir):
    """Two tasks built from one set of settings code: only the task that names the host gets it."""
    adapter = CommandAdapter({})
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with_host = _settings_for(adapter, _ctx(worktree, task_dir, ["mvn", "test"], ["repo.maven.apache.org"]), a)
    without = _settings_for(adapter, _ctx(worktree, task_dir, ["go", "test"], []), b)
    assert with_host["network"]["allowedDomains"] == ["repo.maven.apache.org"]
    assert without["network"]["allowedDomains"] == []


def test_the_factory_home_and_the_credentials_stay_denied_on_a_task_that_has_a_host(tmp_path, worktree, task_dir):
    folder = tmp_path / "attempt"
    folder.mkdir()
    s = _settings_for(CommandAdapter({}), _ctx(worktree, task_dir, ["mvn", "test"], ["repo.maven.apache.org"]), folder)
    deny = set(s["filesystem"]["denyRead"])
    assert set(sandbox.deny_read()) <= deny
    assert str(Path(os.environ["HOME"]).resolve() / ".ssh") in deny
    assert str(Path(os.environ["HOME"]).resolve() / ".claude") in deny
    assert str(Path(os.environ["HOME"]).resolve() / ".codex") in deny


def test_the_settings_still_carry_the_read_and_write_rules(tmp_path, worktree, task_dir):
    folder = tmp_path / "attempt"
    folder.mkdir()
    s = _settings_for(CommandAdapter({}), _ctx(worktree, task_dir, ["mvn", "test"], ["repo.maven.apache.org"]), folder)
    assert s["filesystem"]["allowWrite"] == sandbox.allow_write(worktree, task_dir)
    assert s["filesystem"]["allowRead"] == sandbox.allow_read(worktree, task_dir)


# ---- the real sandbox: a host allowed for one step is reachable from it, and only from it ----------------------------

needs_srt = pytest.mark.skipif(shutil.which("srt") is None, reason="srt is not on PATH (module 9; skipped cleanly)")


def _network_up() -> bool:
    """Maven Central answers from this machine. Skipped cleanly when it does not, so an offline run is not a failure."""
    import urllib.request
    try:
        urllib.request.urlopen("https://repo.maven.apache.org/maven2/", timeout=10).close()
        return True
    except Exception:
        return False


needs_mvn = pytest.mark.skipif(shutil.which("mvn") is None, reason="mvn is not on PATH (skipped cleanly)")
needs_maven_central = pytest.mark.skipif(not _network_up(), reason="repo.maven.apache.org is not reachable (skipped cleanly)")


@needs_srt
@needs_mvn
@needs_maven_central
def test_the_java_test_step_resolves_plugins_and_runs_under_srt_with_its_host_allowed(tmp_path, worktree, task_dir):
    """The shipped Java test step, under srt, with the cache under the task folder and no ~/.m2: plugins resolve from
    Maven Central and surefire runs the test. Measured 2026-11-25 on a temp project."""
    import yaml
    (worktree / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
        '<groupId>demo</groupId><artifactId>proof</artifactId><version>1.0</version>'
        '<properties><maven.compiler.source>17</maven.compiler.source><maven.compiler.target>17</maven.compiler.target>'
        '<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>'
        '<dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId>'
        '<version>5.10.2</version><scope>test</scope></dependency></dependencies>'
        '<build><plugins><plugin><groupId>org.apache.maven.plugins</groupId>'
        '<artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin></plugins></build></project>')
    tests = worktree / "src" / "test" / "java" / "demo"
    tests.mkdir(parents=True)
    (tests / "SumTest.java").write_text(
        "package demo;\nimport static org.junit.jupiter.api.Assertions.assertEquals;\n"
        "import org.junit.jupiter.api.Test;\nclass SumTest { @Test void adds() { assertEquals(4, 2 + 2); } }\n")
    argv = yaml.safe_load((KIT / "java.yaml").read_text())["variants"]["maven"]["test"]
    adapter = CommandAdapter(dict(os.environ))
    ctx = _ctx(worktree, task_dir, argv, ["repo.maven.apache.org"])
    ctx.task_id = "test-java"
    log = tmp_path / "maven.log"
    handle = adapter.start(ctx, harness("command"), log)
    result = adapter.wait(handle, 600)
    assert result.exit == "ok", log.read_text()[-2000:]
    assert (task_dir / "test.junit.xml").is_file()


@needs_srt
@needs_mvn
@needs_maven_central
def test_the_same_java_test_step_with_no_host_allowed_cannot_resolve_its_plugins(tmp_path, worktree, task_dir):
    """The same step, with the allowance empty: Maven cannot reach the repository and the attempt fails."""
    import yaml
    (worktree / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
        '<groupId>demo</groupId><artifactId>proof</artifactId><version>1.0</version></project>')
    argv = yaml.safe_load((KIT / "java.yaml").read_text())["variants"]["maven"]["test"]
    adapter = CommandAdapter(dict(os.environ))
    ctx = _ctx(worktree, task_dir, argv, [])
    ctx.task_id = "test-java"
    log = tmp_path / "maven-denied.log"
    handle = adapter.start(ctx, harness("command"), log)
    result = adapter.wait(handle, 600)
    assert result.exit != "ok"
    assert "could not be resolved" in log.read_text() or "Could not transfer" in log.read_text()


# ---- the real sandbox: a host allowed for one step is reachable from it, and only from it ----------------------------

def _srt_curl(tmp_path, worktree, task_dir, domains, url):
    """Run `curl` under srt with the given allowance, as a command task. Returns the HTTP status or the curl exit."""
    folder = tmp_path / f"attempt-{len(domains)}-{abs(hash(url))}"
    folder.mkdir(exist_ok=True)
    adapter = CommandAdapter(dict(os.environ))
    ctx = _ctx(worktree, task_dir, ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "20", url], domains)
    ctx.task_id = "probe"
    settings = adapter._settings(ctx, folder)
    r = subprocess.run(sandbox.srt_command(shutil.which("srt"), settings, ctx.cmd), cwd=worktree, capture_output=True,
                       text=True, timeout=120)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


@needs_srt
def test_a_command_under_srt_reaches_the_host_it_is_allowed_and_no_other(tmp_path, worktree, task_dir):
    """With repo.maven.apache.org allowed, a request to it answers; with the allowance empty the same request is refused."""
    url = "https://repo.maven.apache.org/maven2/"
    allowed_rc, allowed_out, _ = _srt_curl(tmp_path, worktree, task_dir, ["repo.maven.apache.org"], url)
    denied_rc, denied_out, _ = _srt_curl(tmp_path, worktree, task_dir, [], url)
    assert allowed_rc == 0 and allowed_out == "200", (allowed_rc, allowed_out)
    assert denied_rc != 0, (denied_rc, denied_out)


@needs_srt
def test_a_non_java_command_under_srt_is_refused_repo_maven_apache_org(tmp_path, worktree, task_dir):
    """The Maven host is allowed for the Java test task only. A command in another step, with no hosts, gets 403."""
    rc, out, err = _srt_curl(tmp_path, worktree, task_dir, [], "https://repo.maven.apache.org/maven2/")
    assert rc != 0 and out != "200", (rc, out, err)


@needs_srt
def test_the_factory_home_stays_unreadable_when_a_host_is_allowed(tmp_path, worktree, task_dir, factory_home):
    """A command with a host allowed still cannot read a file under the factory home."""
    canary = factory_home / "canary.txt"
    canary.write_text("secret\n")
    folder = tmp_path / "attempt-read"
    folder.mkdir()
    adapter = CommandAdapter(dict(os.environ))
    ctx = _ctx(worktree, task_dir, ["cat", str(canary)], ["repo.maven.apache.org"])
    settings = adapter._settings(ctx, folder)
    r = subprocess.run(sandbox.srt_command(shutil.which("srt"), settings, ctx.cmd), cwd=worktree, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode != 0 and "secret" not in r.stdout
