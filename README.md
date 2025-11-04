# Autonomous Web Agent

A web automation agent built with gRPC, LangGraph, and Playwright.

## Design Choices

- **gRPC server** for microservices communication between server programs
- **LangGraph** for controlled flow of instructions

## Setup

For accounts with login credentials, save the login by running `scripts/record_cookies.py` to the `chrome-user` profile. This will be set along with the request.

### Steps to run on your computer:

```bash
python -m venv venv
.venv\scripts\activate
pip install -r requirements.txt
```

Use a virtual environment for both tasks.

## Usage

### Start the Playwright Driver server (Terminal 1)

```bash
python -m src.drivers.grpc_playwright_server
```

### Run agent commands (Terminal 2)

**Asana examples:**
```bash
python -m src.agents.runner "change the task status of Schedule kickoff meeting to complete in asana"
python -m src.agents.runner "Create a new message to kgen4295@gmail.com to come early in the meeting in asana"
python -m src.agents.runner "logout from asana"
```

**Linear examples:**
```bash
python -m src.agents.runner "create a new project called Softlight in linear"
python -m src.agents.runner "Write a new issue Make Web Agent B to project Softlight in linear and assign to kgen"
python -m src.agents.runner "change my name to kgen in linear"
python -m src.agents.runner "go to issues and filter by inprogress and change the status of clean up ui to done in linear"
```

## Benchmark Across Models

### Chosen GPT Model

- **GPT-5** → Takes way too long just to process I/O, maybe due to compute time of large parameters or instances not deployed as much as 4o
- **GPT-5-mini** → Does the task well but still slower
- **GPT-4o** → Medium level, does the job but sometimes hallucinates or lacks intelligence of GPT-5
- **GPT-4o-mini** → Makes mistakes frequently

**Selected: GPT-4.1** after extensive testing.

## Custom Architecture

```
┌─────────────────────────────────────────────────────────┐
│  LLM (OpenAI gpt-4.1)                                    │
│  - Sees: [1]<button>Submit</button> format              │
│  - Returns: {"index": 1, "action_type": "click"}       │
└─────────────────────────────────────────────────────────┘
                    ↑                          ↓
┌─────────────────────────────────────────────────────────┐
│  Agent Layer (LangGraph) - NEW BROWSER-USE FORMAT      │
│  ┌───────────────────────────────────────────────────┐ │
│  │ observe_node:                                      │ │
│  │   gRPC interactables → browser-use format         │ │
│  │   Creates: [1]<button>...</button>                │ │
│  │   Stores: selector_map {1: {selector: "..."}}     │ │
│  └───────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────┐ │
│  │ scoring_node:                                      │ │
│  │   Sends browser-use format to LLM                  │ │
│  │   Parses: {"index": 1, ...} from LLM              │ │
│  └───────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────┐ │
│  │ execute_node:                                      │ │
│  │   index 1 → selector_map[1].selector             │ │
│  │   Sends selector to gRPC                          │ │
│  └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                    ↑                          ↓
┌─────────────────────────────────────────────────────────┐
│  gRPC Client (DriverClient) - UNCHANGED                │
│  - observe() → returns interactables                   │
│  - act(selector=...) → executes action                 │
└─────────────────────────────────────────────────────────┘
                    ↑                          ↓
┌─────────────────────────────────────────────────────────┐
│  gRPC Server (Playwright) - UNCHANGED                  │
│  - Returns: interactables with selectors               │
│  - Receives: selectors for actions                    │
│  - No knowledge of browser-use format                  │
└─────────────────────────────────────────────────────────┘
```
