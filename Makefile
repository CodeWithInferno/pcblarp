PY ?= python3
UV := $(shell command -v uv 2>/dev/null)
VENV := .venv
IDEA ?= Make a small device with mic bluetooth and battery which on press of a button turns on and sends all recordings to iphone

.PHONY: install run test demo demo-partial demo-live demo-ui worker docker-worker clean

install:
ifdef UV
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(VENV)/bin/python -e ".[dev,cloud]"
else
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -U pip
	$(VENV)/bin/pip install -e ".[dev,cloud]"
endif

run:  ## API + UI at http://localhost:8000 (live Claude unless CHATPCB_MOCK_LLM=1)
	$(VENV)/bin/uvicorn chatpcb.app:app --reload --port 8000

test:
	$(VENV)/bin/pytest -q

demo:  ## full pipeline with mocked Claude + mocked stages 3-5; no API key needed
	CHATPCB_MOCK_LLM=1 $(VENV)/bin/python -m chatpcb.cli "$(IDEA)"

demo-partial:  ## demo the error feedback loop + partial results (layout always fails)
	CHATPCB_MOCK_LLM=1 CHATPCB_FAIL_STAGE=layout $(VENV)/bin/python -m chatpcb.cli --events "$(IDEA)"

demo-live:  ## real Claude for stage 1 (needs ANTHROPIC_API_KEY, or TF_GATEWAY_URL + TF_API_KEY)
	$(VENV)/bin/python -m chatpcb.cli "$(IDEA)"

demo-ui:  ## mocked pipeline behind the web UI
	CHATPCB_MOCK_LLM=1 $(VENV)/bin/uvicorn chatpcb.app:app --port 8000

worker:  ## layout worker (needs REDIS_URL)
	$(VENV)/bin/python -m chatpcb.worker

docker-worker:
	docker build -f docker/worker.Dockerfile -t chatpcb-worker .

clean:
	rm -rf artifacts .pytest_cache
