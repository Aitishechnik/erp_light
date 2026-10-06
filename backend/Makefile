VENV := .venv
PYTHON ?= python3.12
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
API_HOST := 127.0.0.1
API_PORT := 4111

.PHONY: install run format lint typecheck test check bootstrap

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

run:
	$(VENV)/bin/uvicorn app.main:app --host $(API_HOST) --port $(API_PORT) --reload

format:
	$(VENV)/bin/ruff format .

lint:
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/ruff check .

typecheck:
	$(VENV)/bin/mypy .

test:
	$(VENV)/bin/pytest

bootstrap:
	$(VENV)/bin/python -c "from app.db import Base, engine; import app.models; Base.metadata.create_all(engine); print('схема создана')"

check: lint typecheck test
