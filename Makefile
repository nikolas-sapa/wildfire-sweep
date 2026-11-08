PYTHON ?= .venv/bin/python

.PHONY: test check verify

test:
	$(PYTHON) -m unittest discover -v

check:
	$(PYTHON) sweep.py --check
	$(PYTHON) suppression.py --check
	$(PYTHON) sensitivity.py --check

verify: test check
