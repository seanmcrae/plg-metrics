UV ?= uv
DATA ?= data/synthetic

.PHONY: install lint format typecheck test data demo plots dashboard ci

install:
	$(UV) sync --extra dev --locked

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
	$(UV) run --no-sync plg engagement --data $(DATA)
	$(UV) run --no-sync plg activation --data $(DATA)
	$(UV) run --no-sync plg experiment onboarding_v2 --data $(DATA)
	$(UV) run --no-sync plg power --baseline 0.29 --mde 0.02 --daily-units 240

plots: data
	$(UV) run --no-sync plg plots --data $(DATA) --out docs/img

dashboard: data
	$(UV) sync --extra dev --extra dashboard --locked
	$(UV) run --no-sync streamlit run src/plg/dashboard.py -- --data $(DATA)

ci: lint typecheck test
