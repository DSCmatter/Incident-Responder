PY ?= uv run python
SPLIT ?= dev
INCIDENT ?= S01
REPEATS ?= 1
ARGS ?=
RUN ?=
BY ?=
NOTE ?=

.PHONY: setup up down lint fmt test smoke eval run approve reject ingest rag-recall trace

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

approve:
	$(PY) tasks.py approve --run-id "$(RUN)" --by "$(BY)" --note "$(NOTE)"

reject:
	$(PY) tasks.py reject --run-id "$(RUN)" --by "$(BY)" --note "$(NOTE)"

ingest:
	$(PY) tasks.py ingest

rag-recall:
	$(PY) tasks.py rag-recall --split $(SPLIT)

trace:
	$(PY) tasks.py trace
