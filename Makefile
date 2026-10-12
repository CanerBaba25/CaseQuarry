.PHONY: setup dev migrate test lint typecheck smoke generate-fixtures release-check
setup:
	uv run python scripts/tasks.py setup
dev:
	uv run python scripts/tasks.py dev
migrate:
	uv run python scripts/tasks.py migrate
test test-unit test-integration test-security test-integration-offline:
	uv run python scripts/tasks.py test
test-e2e:
	uv run python scripts/tasks.py test-e2e
lint:
	uv run python scripts/tasks.py lint
typecheck:
	uv run python scripts/tasks.py typecheck
smoke:
	uv run python scripts/tasks.py smoke
generate-fixtures:
	uv run python scripts/tasks.py fixtures --count 100
bench-10k:
	uv run python scripts/tasks.py benchmark --count 10000
bench-100k:
	uv run python scripts/tasks.py benchmark --count 100000
bench-1m:
	uv run python scripts/tasks.py benchmark --count 1000000
bench-2m:
	uv run python scripts/tasks.py benchmark --count 2000000
release-check: lint typecheck test
	uv run python scripts/tasks.py release
