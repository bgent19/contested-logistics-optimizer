# Contested-Logistics Routing Optimizer -- common tasks.
#
# Quick start (no Docker):
#     make install   # editable install with API + dev extras
#     make test      # run the test suite
#     make run       # baseline allocation on the sample theater
#     make api       # serve the REST API at http://localhost:8000/docs

PYTHON ?= python3
DATA   ?= data/theater_sample.json

.PHONY: help install test run demo sweep api docker-build docker-run clean

help:
	@echo "Targets: install | test | run | demo | sweep | api | docker-build | docker-run | clean"

install:
	$(PYTHON) -m pip install -e ".[api,dev]"

test:
	$(PYTHON) -m pytest -q

# Baseline theater-wide allocation (the headline result).
run:
	PYTHONPATH=src $(PYTHON) -m clopt.cli allocate --data $(DATA) --risk-aversion 0

# A guided tour: baseline, a risk-averse plan, the Pareto sweep, and a disruption.
demo:
	@echo "== Baseline allocation (lambda=0) =="
	PYTHONPATH=src $(PYTHON) -m clopt.cli allocate --data $(DATA) --risk-aversion 0
	@echo "\n== Risk-averse allocation (lambda=25) =="
	PYTHONPATH=src $(PYTHON) -m clopt.cli allocate --data $(DATA) --risk-aversion 25
	@echo "\n== Cost/risk frontier =="
	PYTHONPATH=src $(PYTHON) -m clopt.cli sweep --data $(DATA)
	@echo "\n== Under 'strait_mined' threat picture =="
	PYTHONPATH=src $(PYTHON) -m clopt.cli allocate --data $(DATA) --threat strait_mined

sweep:
	PYTHONPATH=src $(PYTHON) -m clopt.cli sweep --data $(DATA)

api:
	PYTHONPATH=src CLOPT_DATA=$(DATA) $(PYTHON) -m uvicorn clopt.api:app --reload --host 0.0.0.0 --port 8000

docker-build:
	docker build -t clopt:latest .

docker-run:
	docker run --rm -p 8000:8000 clopt:latest

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
