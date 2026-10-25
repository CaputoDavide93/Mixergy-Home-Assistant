# One entry point for the checks CI runs. `make check` before every push.
PYTHON := .venv/bin/python

.PHONY: venv test lint typecheck diagram check screenshots

venv: ## Home Assistant 2026.8.2 test environment, built with uv
	uv venv -q --allow-existing --python 3.14 .venv
	VIRTUAL_ENV=.venv uv pip install -q -r requirements-test.txt \
		homeassistant==2026.8.2 pytest-homeassistant-custom-component==0.13.356

test: ## The pytest suite, with the coverage floor CI enforces
	$(PYTHON) -m pytest tests -q --cov=custom_components.mixergy_tank --cov-fail-under=95

lint: ## ruff
	$(PYTHON) -m ruff check .

typecheck: ## mypy, strict, against the oldest supported Home Assistant (as CI does)
	test -x .venv-typecheck/bin/python || ( \
		uv venv -q --python 3.13 .venv-typecheck && \
		VIRTUAL_ENV=.venv-typecheck uv pip install -q -r requirements-test.txt \
			homeassistant==2025.8.0 "pycares<5" )
	.venv-typecheck/bin/python -m mypy custom_components/mixergy_tank

diagram: ## Redraw docs/assets/*.svg and the README entity tables
	python3 tools/gen_diagram.py
	python3 tools/gen_entity_docs.py

check: lint typecheck test ## Everything CI checks
	python3 tools/gen_diagram.py --check
	python3 tools/gen_entity_docs.py --check

screenshots: ## Retake docs/assets/screenshots/ from a throwaway Home Assistant (not CI)
	test -x .venv-screenshots/bin/python || ( \
		uv venv -q --python 3.14 .venv-screenshots && \
		VIRTUAL_ENV=.venv-screenshots uv pip install -q -r tools/screenshots/requirements.txt )
	.venv-screenshots/bin/python -m playwright install chromium
	.venv-screenshots/bin/python tools/screenshots/take_screenshots.py
