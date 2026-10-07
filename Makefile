UV ?= uv
DATA ?= data/synthetic

.PHONY: install lint format typecheck test data demo plots dashboard ci

install:
	$(UV) venv --allow-existing
	$(UV) pip install -e ".[dev]"

lint:
	$(UV) run --no-sync ruff check .
	$(UV) run --no-sync ruff format --check .

format:
	$(UV) run --no-sync ruff format .
	$(UV) run --no-sync ruff check --fix .

typecheck:
	$(UV) run --no-sync mypy

test:
	$(UV) run --no-sync pytest --cov --cov-report=term-missing:skip-covered

data:
	$(UV) run --no-sync plg generate --out $(DATA)

demo: data
	$(UV) run --no-sync plg funnel --data $(DATA) --by plan
	$(UV) run --no-sync plg retention --data $(DATA)
	$(UV) run --no-sync plg experiment onboarding_v2 --data $(DATA)
	$(UV) run --no-sync plg power --baseline 0.30 --mde 0.02

plots: data
	$(UV) run --no-sync plg plots --data $(DATA) --out docs/img

dashboard: data
	$(UV) pip install -e ".[dashboard]"
	$(UV) run --no-sync streamlit run src/plg/dashboard.py -- --data $(DATA)

ci: lint typecheck test
