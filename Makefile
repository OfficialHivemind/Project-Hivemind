VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: help venv protocols check clean

help:
	@echo "make venv       - create venv (--system-site-packages) and install hivemind"
	@echo "make protocols  - generate Wayland bindings from protocols/*.xml"
	@echo "make check      - doctor: verify every dependency and protocol"

venv:
	python3 -m venv --system-site-packages $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e .

# pywayland needs generated bindings for the three protocols we vendor.
protocols:
	$(PY) -m pywayland.scanner \
		--input /usr/share/wayland/wayland.xml \
		protocols/virtual-keyboard-unstable-v1.xml \
		        protocols/wlr-virtual-pointer-unstable-v1.xml \
		        protocols/wlr-screencopy-unstable-v1.xml \
		--output-dir src/hivemind/platform/wl/gen

check:
	$(PY) -m hivemind.cli.main doctor

clean:
	rm -rf $(VENV) src/hivemind/platform/wl/gen
