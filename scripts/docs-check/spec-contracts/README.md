# spec-contracts

Checks that the phase 1 spec and the engine's code agree. Run from the repo root:

    cd factory/engine && uv run --python 3.10 --group dev pytest ../../scripts/docs-check/spec-contracts -q

It needs the engine's environment (`factory_engine`, PyYAML, jsonschema), so it is run with the engine's `pytest`.
These tests read `docs/`, so they stay out of `factory/`, which is copied into other repos and must not reference `docs/` (AGENTS.md).

- `test_types_match_spec.py`: each dataclass in `types.py` has the fields the spec's code block lists, in the same order.
- `test_spec_examples_validate.py`: every YAML and JSON example for a state or config file validates against its schema in `factory/schemas/`.
- `test_signatures_match_spec.py`: every function and method the spec declares has the parameters the spec lists, once its module is built; pending ones are counted and the count may only go down. The four fakes are checked against their protocols.
- `spec_signatures.py`: the reader for the spec's signatures (shared by the test above).
