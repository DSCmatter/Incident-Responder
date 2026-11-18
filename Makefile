PY ?= uv run python
SPLIT ?= dev
INCIDENT ?= S01
REPEATS ?= 1
ARGS ?=

.PHONY: setup up down lint fmt test smoke eval run trace

setup:
	$(PY) tasks.py setup

up:
	$(PY) tasks.py up

down:
	$(PY) tasks.py down

lint:
	$(PY) tasks.py lint

fmt:
	$(PY) tasks.py fmt

test:
	$(PY) tasks.py test $(ARGS)

smoke:
	$(PY) tasks.py smoke $(ARGS)

eval:
	$(PY) tasks.py eval --split $(SPLIT) --repeats $(REPEATS) $(ARGS)

run:
	$(PY) tasks.py run --incident $(INCIDENT) $(ARGS)

trace:
	$(PY) tasks.py trace
