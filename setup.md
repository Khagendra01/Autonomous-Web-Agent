# Setup Instructions

## 1. Environment Setup

### Deactivate Conda and Create Virtual Environment

```bash
# Deactivate conda if active
conda deactivate

# Create virtual environment
python -m venv .venv

# Activate on Windows
.venv\Scripts\activate

# Activate on Mac/Linux
source .venv/bin/activate
```

## 2. Install Dependencies

```bash
# Install all dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium
```

## 3. Environment Variables

Create a `.env` file in the project root:

```bash
# Required: OpenAI API Key for LLM reasoning
OPENAI_API_KEY=your_openai_api_key_here
```

Or set it directly in your shell:

```bash
# Windows PowerShell
$env:OPENAI_API_KEY="your_key_here"

# Windows CMD
set OPENAI_API_KEY=your_key_here

# Mac/Linux
export OPENAI_API_KEY=your_key_here
```

## 4. Record Authentication Cookies

Before running the agent, record your Linear login session:

```bash
# Run the cookie recording script
python -m scripts.record_cookies

# Follow prompts to login to Linear
# Press Enter after login to save cookies
```

This saves cookies to `auth/linear-cookies.json`.

## 5. Run the Agent

Start the Playwright driver in one terminal:

```bash
python -m src.drivers.playwright_driver
```

In another terminal, run the agent:

```bash
python -m src.agents.graph run linear "create a project in linear named alpha"
```

## Workflow Overview

The agent uses **LangGraph** with the following nodes:

1. **Observe** → Capture page state, DOM, screenshot
2. **Reason** → LLM analyzes state and decides what to do
3. **Act** → Execute the planned action (click, type, scroll)
4. **Validate** → Check if goal is achieved
5. **Loop** → Repeat until done or max steps reached

## Architecture

- **Driver** (`src/drivers/playwright_driver.py`): Flask server wrapping Playwright
- **Graph** (`src/agents/graph.py`): LangGraph workflow orchestration
- **Planner** (`src/agents/planner.py`): LLM-based reasoning and validation
- **State** (`src/agents/state.py`): Pydantic models for agent state
- **Executor** (`src/agents/executor.py`): HTTP client for driver
- **Perception** (`src/agents/perception.py`): Screenshot and state capture

## Troubleshooting

### Cookies Not Loading
- Make sure you ran `python -m scripts.record_cookies` first
- Check that `auth/linear-cookies.json` exists
- The driver uses a persistent Chrome profile in `chrome-user/`

### LLM Errors
- Verify `OPENAI_API_KEY` is set correctly
- Check your OpenAI API quota/limits
- Model used: `gpt-4o` (you can change in `planner.py`)

### Browser Issues
- Run `playwright install chromium` if browser is missing
- Make sure Chrome is installed on your system
- Check that port 3999 is available for the driver

