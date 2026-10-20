#! /bin/bash
# THE UI PREVIEW (the owner, 2026-10-22): the demo only, Start is off in a demo
# (gui/window._start). The app's code and data are bundled under $APPDIR/app.
export PYTHONPATH="$APPDIR/app/src${PYTHONPATH:+:$PYTHONPATH}"
{{ python-executable }} -X utf8 -m hivemind.gui --demo --loop "$@"
