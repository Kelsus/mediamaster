.PHONY: test dev deploy import-dry import

test:
	cd backend && uv run pytest -q

# Local dev: FastAPI on :8000 against the deployed dev table, Vite on :5173 proxying /api
dev:
	./scripts/dev.sh

deploy:
	./scripts/deploy.sh

import-dry:
	cd backend && uv run python ../scripts/import_notion.py $(CSV) --dry-run

import:
	cd backend && uv run python ../scripts/import_notion.py $(CSV)
