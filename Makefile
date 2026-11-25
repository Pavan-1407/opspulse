.PHONY: dev api web test seed docker

api:        ## run the API with hot reload (SQLite by default)
	cd backend && uvicorn app.main:app --reload --port 8000

web:        ## run the Vite dev server (proxies /api to :8000)
	cd frontend && npm run dev

test:
	cd backend && ruff check app tests && pytest -q

seed:       ## wipe and regenerate the synthetic dataset + retrain the model
	cd backend && python -m app.seed --reset

docker:     ## full stack: Postgres + app on http://localhost:8000
	docker compose up --build
