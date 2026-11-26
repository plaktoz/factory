# The engine sets FACTORY_TASK_DIR and reads the JUnit files from there. Run by hand, they go to .out/.
PYTHON ?= python3
OUT := $(if $(FACTORY_TASK_DIR),$(FACTORY_TASK_DIR),.out)
PYTEST = PYTHONPATH=services/api PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m pytest -q -p no:cacheprovider

.PHONY: build test-api e2e

build:
	$(PYTHON) -c "import ast, pathlib; [ast.parse(p.read_text(), str(p)) for p in pathlib.Path('services').rglob('*.py')]"
	node --check web/format.js

test-api:
	mkdir -p $(OUT)
	$(PYTEST) services/api/tests --junitxml=$(OUT)/be.junit.xml

e2e:
	mkdir -p $(OUT)
	$(PYTEST) e2e --junitxml=$(OUT)/e2e.junit.xml
