.PHONY: sync lint types test secrets markers evals ci

sync:
	uv sync --all-packages

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

markers:
	uv run python scripts/check_markers.py

secrets:
	uv run python scripts/secret_scan.py

# Same gates as .github/workflows/ci.yml (docs/v4/27_ENGINEERING_STANDARDS.md section 5).
ci: sync lint types markers test secrets
