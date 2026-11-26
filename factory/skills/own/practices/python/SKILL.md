---
name: practices-python
description: Python design, error handling and testing rules that a formatter or linter cannot check.
---

These rules cover what ruff and pytest cannot check. Do not restate formatting or lint rules here: the repo's linter
configuration owns them, and the verify stage runs it.

## Design

- Put each decision in a small pure function that takes plain values and returns a value. Keep file, network and
  process work at the edges, so the decision can be tested without them.
- Parse outside data once, at the boundary (a file, a CLI argument, an HTTP body), into a typed value such as a
  dataclass. Code behind the boundary trusts the type and does not re-check it.
- Name a value for what it means, not how it is stored. Two values that mean different things get two types, even when
  both are `str`.
- Do not add an abstraction for one caller. A second caller is the reason to share code.

## Errors

- Raise the narrowest exception that names the failure. Catch an exception only where you can act on it: retry, add
  context, or turn it into the module's own error.
- Never write a bare `except:` or an `except Exception:` that swallows the error. When you must catch broadly at a
  boundary, log the cause and re-raise, or return an explicit failure.
- Keep the cause: write `raise NewError(...) from err`.
- Do not return `None` to mean "failed". Raise, or return a result the caller must look at.
- Use `assert` for a condition that cannot happen, never to check input.

## State and I/O

- Do not use a mutable default argument, and do not keep module-level mutable state that a test cannot reset.
- Write a file by writing a temporary file beside it and renaming it over the target, so a crash leaves the old file.
- Pass the clock, the random source and the paths in as arguments, so a test can fake them.

## Tests

- Test what a caller can observe: what goes in, what comes out, what is written. Do not test private helpers or call
  order.
- Write the failing test first, and watch it fail for the reason you expect before you make it pass.
- One test, one reason to fail. Name it for the case, for example `test_a_late_payment_adds_a_fee`.
- Use a real temporary folder (`tmp_path`) and fake only the outside world you cannot run.
- Cover the empty input, the single item and the error path, not only the common case.
