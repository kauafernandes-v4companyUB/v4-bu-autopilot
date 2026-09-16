.PHONY: venv doctor test check clean

VENV := .venv
PY := $(VENV)/bin/python

venv:
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip
	$(PY) -m pip install --quiet -r requirements-dev.txt

doctor: venv
	$(PY) scripts/doctor.py $(ARGS)

test: venv
	$(PY) -m pytest tests/ -q

check: venv
	$(PY) -m py_compile $$(git ls-files 'scripts/*.py' 'tests/*.py')
	$(PY) -m pytest tests/ -q
	$(PY) scripts/doctor.py

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__
