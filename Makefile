.PHONY: setup lock lint test build run

setup:
	docker compose up --build -d
	@echo "Waiting for ES+PG health..."
	sleep 15
	docker exec -it chess_assistant_app poetry run python utils/setup.py

lock:
	cd chat && poetry lock && cd ..

lint:
	cd chat && python -m ruff check . && python -m ruff format --check . || true
	cd chat && python -m mypy utils --ignore-missing-imports || true

test:
	cd chat && python -m pytest -q

build:
	docker compose build

run:
	docker compose up

clean:
	docker compose down -v
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -name "*.pyc" -delete
