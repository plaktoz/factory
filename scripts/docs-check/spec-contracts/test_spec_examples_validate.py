"""Each YAML and JSON example the spec shows for a state or config file must validate (W0.4).

Lives in scripts/docs-check because it reads the spec. The schemas are checked against
factory/engine/factory_engine/schemagen.py's output by the engine tests.
"""

import json
import re
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml
from yaml.resolver import Resolver

from spec_blocks import REPO

MODULES = REPO / "docs/design/modules"
SCHEMAS = REPO / "factory" / "schemas"


class FactoryLoader(yaml.SafeLoader):
    """YAML 1.2 booleans: only true and false. Plain safe_load reads `off` and `on` as booleans, which breaks
    the spec's own `helpers: {mode: off}` and `hooks: [{on: [...]}]`. The engine's loader (module 3) must do this too."""


FactoryLoader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:bool"] for k, v in Resolver.yaml_implicit_resolvers.items()
}
FactoryLoader.add_implicit_resolver("tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf"))


def load_yaml(text):
    return yaml.load(text, Loader=FactoryLoader)


def validator(name):
    store = {}
    for p in SCHEMAS.glob("*.schema.json"):
        s = json.loads(p.read_text())
        store[s["$id"]] = s
        store[p.name] = s
    resolver_schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text())

    from referencing import Registry, Resource
    reg = Registry().with_resources([(k, Resource.from_contents(v)) for k, v in store.items()])
    return jsonschema.Draft202012Validator(resolver_schema, registry=reg)


def yaml_blocks(path: Path, first_line_re: str):
    text = path.read_text()
    return [b for b in re.findall(r"```yaml\n(.*?)```", text, re.S) if re.search(first_line_re, b.split("\n", 1)[0])]


def one(path: Path, first_line_re: str):
    blocks = yaml_blocks(path, first_line_re)
    assert len(blocks) == 1, f"expected one yaml block matching {first_line_re!r} in {path.name}, found {len(blocks)}"
    return blocks[0]


def test_merge_policy_example():
    doc = load_yaml(one(MODULES / "13-delivery.md", r"merge-policy\.yaml"))
    validator("merge-policy").validate(doc)


def test_factory_yaml_example_in_module_3():
    block = one(MODULES / "03-kit-and-configuration.md", r"factory\.yaml")
    doc = load_yaml(block.split("# ~/.factory/config.yaml")[0])
    validator("factory-config").validate(doc)


def test_factory_yaml_routing_example_in_module_9():
    block = yaml_blocks(MODULES / "09-worker-adapters-and-governed-helpers.md", r"~/\.factory/config\.yaml")[0]
    doc = load_yaml(block.split("# .factory/config/factory.yaml", 1)[1].split("\n", 1)[1])
    validator("factory-config").validate({"base_branch": "main", "tracker": "github", "harness": "claude", **doc})


def test_factory_yaml_mcp_example_in_module_9():
    blocks = yaml_blocks(MODULES / "09-worker-adapters-and-governed-helpers.md", r"~/\.factory/config\.yaml")
    doc = load_yaml(blocks[1].split("# .factory/config/factory.yaml", 1)[1].split("\n", 1)[1])
    validator("factory-config").validate({"base_branch": "main", "tracker": "github", "harness": "claude", **doc})


@pytest.mark.parametrize("which", ["frontend-review", "license-check"])
def test_plugin_manifest_examples(which):
    block = one(MODULES / "05-workflows-and-plugins.md", rf"plugins/{which}/plugin\.yaml")
    validator("plugin").validate(load_yaml(block))


def test_decision_file_example():
    doc = load_yaml(one(MODULES / "11-human-stops.md", r"packet:"))
    validator("decision").validate(doc)


def test_decision_with_a_missing_picker_field_fails():
    doc = load_yaml(one(MODULES / "11-human-stops.md", r"packet:"))
    del doc["packet"]["decisions"][0]["context"]
    with pytest.raises(jsonschema.ValidationError):
        validator("decision").validate(doc)


def test_json_examples_in_the_spec_validate():
    """request.json (module 4) is not the Request dataclass shape, so it is reported, not asserted."""
    text = (MODULES / "08-gates-error-handling-and-rework.md").read_text()
    block = re.findall(r"```json\n(.*?)```", text, re.S)[0]
    validator("feedback").validate(json.loads(block))


def test_plain_safe_load_breaks_the_spec_examples():
    """Why FactoryLoader exists: with plain safe_load, `mode: off` becomes False."""
    block = one(MODULES / "05-workflows-and-plugins.md", r"plugins/frontend-review/plugin\.yaml")
    plain = yaml.safe_load(block)
    assert plain["insert"]["stage"]["tasks"][0]["helpers"]["mode"] is False
    assert load_yaml(block)["insert"]["stage"]["tasks"][0]["helpers"]["mode"] == "off"


def _json_example(path: Path, needle: str):
    blocks = [b for b in re.findall(r"```json\n(.*?)```", path.read_text(), re.S) if needle in b]
    assert len(blocks) == 1, f"expected one json block with {needle!r} in {path.name}, found {len(blocks)}"
    return json.loads(blocks[0])


def test_request_json_example_matches_the_frozen_request():
    validator("request").validate(_json_example(MODULES / "04-intake-and-triage.md", '"request_id": "gh-42"'))


def test_run_json_example_matches_the_frozen_run():
    validator("run").validate(_json_example(MODULES / "06-engine-core.md", '"run_id": "new-color-q1w2e"'))
