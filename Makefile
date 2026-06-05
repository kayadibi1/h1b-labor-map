# H-1B Labor Map — convenience targets.
# All targets assume `uv sync` has been run.

.PHONY: setup verify ingest clean resolve join score views all incremental force-refresh dry-run test lint fmt

setup:
	uv sync

verify-env:
	uv run python -c "import polars, duckdb, pandera, rapidfuzz, requests, yaml, dotenv; print('env ok')"

verify:
	uv run python run.py --stage verify

ingest:
	uv run python run.py --stage ingest

clean:
	uv run python run.py --stage clean

join:
	uv run python run.py --stage join

score:
	uv run python run.py --stage score

views:
	uv run python run.py --stage views

all:
	uv run python run.py --stage all

incremental:
	uv run python run.py --stage all --incremental

force-refresh:
	uv run python run.py --stage all --force-refresh

dry-run:
	uv run python run.py --stage all --dry-run

test:
	uv run pytest -q

lint:
	uv run ruff check .

fmt:
	uv run ruff format .
