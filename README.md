# Autonomous Web Agent

Local-first autonomous web agent using **LangGraph**, **OpenAI GPT-4o**, and **Playwright**. The agent reasons about web pages and takes actions to achieve goals.

## Features

- 🧠 **LLM-powered reasoning**: GPT-4o analyzes page state and plans actions
- 🔄 **LangGraph workflow**: Observe → Plan → Act loop
- 🌐 **Playwright automation**: Browser control with accessibility tree
- 💾 **State capture**: Screenshots and interaction history
- 🔐 **Persistent auth**: Chrome profile preserves login sessions
- 🐭 **Flood Fill Agent**: Autonomous exploration inspired by the Micromouse algorithm

## Quick Start

### 1. Setup Environment

**Windows:**
```bash
# Run the setup script
setup.bat
```

**Manual setup:**
```bash
# Deactivate conda if active
conda deactivate

# Create and activate venv
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -e .
playwright install chromium
```

### 2. Set OpenAI API Key

```bash
# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-key-here"

# Mac/Linux
export OPENAI_API_KEY="sk-your-key-here"
```

### 3. Record Authentication (One-time)

```bash
python -m scripts.record_cookies
```

This opens a browser where you log into Linear. Your session is saved in the `chrome-user/` directory.

### 4. Run the Flood Fill Agent

**Terminal 1 - Start Driver:**
```bash
python -m src.drivers.playwright_driver
```

**Terminal 2 - Run Agent:**
```bash
python -m src.agents.graph_flood_fill run "create a project in linear named alpha"
```

The agent will:
1. Open Linear in Chrome (already logged in)
2. Use GPT-4o to reason about what to do
3. Click buttons, type text, scroll as needed

Flood Fill mode also:
- 🗺️ Builds a state space graph (like maze solving)
- 🧠 Learns optimal paths via a flood-fill update
- 💾 Saves knowledge to `knowledge/graphs/{app}_graph.json`
- ⚡ Reuses learned paths on subsequent runs

See [FLOOD_FILL_AGENT.md](./FLOOD_FILL_AGENT.md) for detailed documentation.

## Architecture

```
┌─────────────┐
│   LangGraph │  Orchestrates workflow
│   Workflow  │  (Observe → Plan → Act)
└──────┬──────┘
       │
       ├──► FloodFillPlanner
       ├──► Executor (HTTP client)
       ├──► Perception (Screenshot capture)
       └──► State (Pydantic models)
               │
               ▼
       ┌───────────────┐
       │  Flask Driver │  Wraps Playwright
       │  (Port 3999)  │  Uses persistent Chrome profile
       └───────────────┘
```

## Workflow Nodes

1. **Observe**: Capture DOM, accessibility tree, screenshot
2. **Plan**: FloodFillPlanner analyzes state graph and selects the next action
3. **Act**: Execute action (click, type, scroll)

## Output

Artifacts saved to `dataset/{app}/{task}/{timestamp}/`:
- `screens/` - Sequential screenshots

## Configuration

Edit these files to customize:
- `src/agents/planner_flood_fill.py` - Change LLM model (default: `gpt-4o`)
- `src/agents/state.py` - Adjust max steps
- `src/drivers/playwright_driver.py` - Modify browser settings

## Troubleshooting

**"OPENAI_API_KEY not set"**
- Set the environment variable before running

**Browser stuck at login**
- Run `python -m scripts.record_cookies` first
- Check that `chrome-user/` directory exists

**Driver connection failed**
- Make sure driver is running: `python -m src.drivers.playwright_driver`
- Check port 3999 is available

## Development

See `setup.md` for detailed setup instructions and `.cursorrules` for Cursor IDE configuration.

