#!/usr/bin/env python3
"""Text des GitHub-Releases aus cockpit/CHANGELOG.md. Bricht ab, wenn die Version dort fehlt —
so kann niemand ein Release ohne Versionshinweise veröffentlichen."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cockpit.changelog import abschnitt  # noqa: E402
from cockpit.version import VERSION      # noqa: E402

text = abschnitt(VERSION)
if not text:
    sys.exit(f"cockpit/CHANGELOG.md hat keinen Abschnitt «## {VERSION} — …». Bitte Versionshinweise ergänzen.")
print(text)
