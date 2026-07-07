#!/usr/bin/env bash
# מקים את .venv-bu — venv נפרד ל-browser-use (שכבת הניווט).
# נפרד כי browser-use מצמיד google-genai==1.65 ↔ ה-app על 2.8 (קונפליקט).
set -euo pipefail
cd "$(dirname "$0")/.."
python3.12 -m venv .venv-bu
.venv-bu/bin/pip install -q --upgrade pip
.venv-bu/bin/pip install -q 'browser-use==0.13.1'  # אותו pin כמו ה-Dockerfile — בלי דריפט dev/prod
.venv-bu/bin/python -c "from browser_use import Agent; print('browser-use OK in .venv-bu')"
