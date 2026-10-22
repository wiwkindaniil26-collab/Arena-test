.PHONY: install install-dev run test lint format docker-up docker-down

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt

install-dev:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

run:
	.venv/bin/python -m bot

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff format .
	.venv/bin/ruff check . --fix

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
