.PHONY: install test test-be test-fe e2e run-be run-fe up down

install:
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

test: test-be test-fe

test-be:
	cd backend && python -m pytest tests -q

test-fe:
	cd frontend && npm test

e2e:
	python -m pytest e2e -q

run-be:
	cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-fe:
	cd frontend && npm run dev

up:
	docker compose up --build

down:
	docker compose down
