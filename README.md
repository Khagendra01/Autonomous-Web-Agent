# Autonomous Web Agent

A **task-agnostic** AI-powered autonomous web agent that captures UI states and workflows using LangGraph, OpenAI, and Playwright.

## Overview

This agent autonomously navigates **any** web application to capture UI states for **any** goal you provide. It uses:

- **LangGraph**: For orchestrating the agent workflow
- **OpenAI GPT-4**: For scoring DOM elements and deciding which actions lead to goals
- **Playwright**: For browser automation and DOM interaction
- **Task-Agnostic Design**: No pre-defined workflows - just provide a goal and URL!

## Architecture

### Simplified LLM-Driven Approach

Instead of implementing a flood-fill algorithm, we use a **scoring-based approach**:

1. **Observe**: Capture current DOM state and interactive elements
2. **Score**: LLM analyzes elements and scores them (0-10) based on likelihood to reach goal
3. **Execute**: Execute the highest-scored action
4. **Check Goal**: LLM evaluates if goal is reached
5. **Repeat**: Loop until goal is achieved or max steps reached

### Key Components

- `state.py` - State definition for the LangGraph workflow
- `nodes.py` - Individual workflow nodes (observe, score, execute, check)
- `workflow.py` - LangGraph workflow definition
- `tasks.py` - Task definitions for different web apps
- `runner.py` - Main entry point for running tasks
- `utils/` - Helper utilities for DOM, storage, and vision

## Setup

### 1. Install Dependencies

```bash
# Activate virtual environment
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium
```

### 2. Set OpenAI API Key

```bash
# Windows
set OPENAI_API_KEY=your-api-key-here

# Mac/Linux
export OPENAI_API_KEY=your-api-key-here
```

### 3. Start the Driver

In one terminal:

```bash
python -m src.drivers.playwright_driver
```

The driver will start on http://127.0.0.1:3999

## Usage

### Basic Usage

The agent is **task-agnostic** - just provide any goal and starting URL:

```bash
python -m src.agents.runner \
  --goal "Create a new project" \
  --url "https://linear.app/test916/team/TES/active"
```

### Full Options

```bash
python -m src.agents.runner \
  --goal "<your goal in natural language>" \
  --url "<starting URL>" \
  --app "<app name>" \           # Optional: auto-detected from URL
  --max-steps 20 \               # Optional: default is 15
  --output "captures"            # Optional: output directory
```

### Examples

```bash
# Create a Linear project
python -m src.agents.runner \
  --goal "Create a new project in Linear" \
  --url "https://linear.app/test916/team/TES/active"

# Filter a Notion database
python -m src.agents.runner \
  --goal "Open a database and apply a filter" \
  --url "https://www.notion.so/"

# Create a GitHub issue
python -m src.agents.runner \
  --goal "Create a new issue" \
  --url "https://github.com/yourusername/yourrepo"

# ANY other task you can think of!
python -m src.agents.runner \
  --goal "Change my profile picture" \
  --url "https://yourapp.com/settings"
```

### See More Examples

```bash
python -m src.agents.tasks
```

This will show you example goals and URLs for Linear, Notion, GitHub, Asana, Trello, and more - but remember, **the agent works with ANY goal and URL!**

## Output

The agent captures screenshots at each step and saves them to:

```
captures/
  <app>/
    <task>/
      <timestamp>/
        screens/
          step_000.png
          step_001.png
          ...
        index.json  # Manifest with metadata
```

## How It Works

### 1. DOM Analysis
```python
# The driver extracts interactive elements
interactables = [
  {'role': 'button', 'label': 'Create project', 'selector': '...'},
  {'role': 'link', 'label': 'Settings', 'selector': '...'},
  ...
]
```

### 2. LLM Scoring
```python
# LLM scores each element
[
  {
    "selector": "role=button[name='Create project']",
    "label": "Create project",
    "score": 9.5,
    "reasoning": "Directly opens project creation flow"
  },
  ...
]
```

### 3. Action Execution
```python
# Execute highest-scored action
execute_action(scored_actions[0])
```

### 4. Goal Evaluation
```python
# LLM checks if goal is reached
{
  "goal_reached": false,
  "reasoning": "Still need to fill in project details",
  "confidence": 0.8
}
```

## Task-Agnostic Design

### No Configuration Needed!

Unlike traditional automation tools, this agent requires **zero configuration**:

- ✅ No pre-defined selectors or workflows
- ✅ No app-specific code
- ✅ No hardcoded navigation paths
- ✅ Works with any web application
- ✅ Just describe what you want in natural language

### How It Generalizes

1. **DOM Analysis**: Uses accessibility tree (not app-specific selectors)
2. **LLM Reasoning**: Understands UI semantics naturally
3. **Goal-Oriented**: Adapts strategy based on your goal
4. **Self-Correcting**: Learns from errors and adjusts

### Add New Applications

Nothing to add! Just:

1. Navigate to the app
2. Describe your goal
3. Run the agent

If authentication is needed, log in once manually - the persistent Chrome profile will remember your session.

## Design Decisions

### Why LLM Scoring Instead of Flood-Fill?

**Flood-fill challenges:**
- Computationally expensive for large DOM trees
- Hard to prune irrelevant branches
- Difficult to handle dynamic content

**LLM scoring advantages:**
- ✅ Natural understanding of UI semantics
- ✅ Can reason about goal relevance
- ✅ Handles dynamic content gracefully
- ✅ Easy to debug (reasoning is explicit)

### Why Task-Agnostic?

Traditional automation approaches fail at generalization:

**Traditional Approach (Selenium/Puppeteer):**
```python
# Requires hardcoded selectors for EVERY app
driver.find_element("#create-button").click()
driver.find_element(".modal-input").send_keys("Project Name")
# Breaks when UI changes!
```

**Our Approach:**
```bash
# Works across ANY app with ANY goal
python -m src.agents.runner \
  --goal "Create a project" \
  --url "https://anyapp.com"
# LLM figures out the UI dynamically!
```

The system generalizes across web apps because:

1. **DOM-agnostic**: Uses accessibility tree, not app-specific selectors
2. **Goal-driven**: Goals are natural language, not hardcoded workflows
3. **LLM-powered**: Adapts to different UI patterns automatically
4. **Screenshot-based**: Captures visual state regardless of implementation
5. **Zero-config**: No per-app setup or training required

## Troubleshooting

### Driver Connection Issues

```bash
# Make sure driver is running
python -m src.drivers.playwright_driver

# Check if port 3999 is available
netstat -an | grep 3999  # Mac/Linux
netstat -an | findstr 3999  # Windows
```

### Authentication Issues

The driver uses a persistent Chrome profile (`chrome-user/`) to maintain authentication state. Log in manually once, and the agent will reuse those sessions.

### LLM Not Finding Elements

- Check that elements are in the accessibility tree
- Verify element roles are recognized (button, link, textbox, etc.)
- Increase `max_steps` for complex workflows

## Future Improvements

- [ ] Add visual analysis (screenshot comparison)
- [ ] Implement retry logic for failed actions
- [ ] Add support for typing dynamic text (forms)
- [ ] Multi-step form filling
- [ ] Better stuck detection and recovery
- [ ] Export to standard formats (HAR, Puppeteer scripts, etc.)

## License

MIT

