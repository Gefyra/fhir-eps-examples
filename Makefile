.DEFAULT_GOAL := help

VENV    ?= .venv
PYTHON  ?= $(VENV)/bin/python
PIP     ?= $(VENV)/bin/pip
PYTEST  ?= $(VENV)/bin/pytest
RESULTS ?= results
SITE    ?= site
PORT    ?= 8000

# Validate one submission with SUBMISSION=examples/<contributor>/<slug>,
# everything without it.
SUBMISSION ?=
ifeq ($(strip $(SUBMISSION)),)
VALIDATE_TARGET := --all
else
VALIDATE_TARGET := $(SUBMISSION)
endif

.PHONY: help install check validate report site serve test clean

help:
	@echo "make install    create $(VENV) and install the tooling"
	@echo "make check      structural checks (this is what blocks a pull request)"
	@echo "make validate   run the FHIR validator     [SUBMISSION=examples/<c>/<s>]"
	@echo "make report     pull request comment and job summary from $(RESULTS)"
	@echo "make site       build the static site into $(SITE)"
	@echo "make serve      build the site and serve it on http://localhost:$(PORT)"
	@echo "make test       run the unit tests"
	@echo "make clean      remove generated files"

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

check:
	$(PYTHON) -m tools check

validate:
	$(PYTHON) -m tools validate $(VALIDATE_TARGET) --out $(RESULTS)/

report:
	$(PYTHON) -m tools report --results $(RESULTS)/ --pr-comment .ci/pr-comment.md --job-summary --no-baseline

site:
	$(PYTHON) -m tools report --results $(RESULTS)/ --site $(SITE)/ --no-baseline

serve: site
	$(PYTHON) -m http.server $(PORT) --directory $(SITE)

test:
	$(PYTEST)

clean:
	rm -rf $(RESULTS) $(SITE) .ci .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
