# AutoUI Agent — Local MVP

Local-first autonomous UI-state capture with Playwright (Chromium) and LangGraph (Python). Python-only.

## Setup

Python:
- Create venv and install: pip install -U pip && pip install -e .

Install browsers:
- python -m playwright install chromium

## Usage

1) Record cookies:
   - Default (persistent Chrome profile):
     - python scripts/record_cookies.py
   - Or CDP (connect to your existing Chrome):
     - Close Chrome, then start: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222
     - USE_CDP=1 python scripts/record_cookies.py
2) Start driver: python -m src.drivers.playwright_driver
3) Run agent: python -m src.agents.graph run --app linear --goal "Create a project in Linear named Alpha"

Artifacts and graphs are saved under dataset/<app>/<task>/<timestamp>/

