Very short read me written by hand



##Design Choices
GRPC server for microservices call inbetween the server program
Langgraph for controlled flow of the instruction



for account with login credential we will save the login by running script/record_cookies to the chrome-user profile, and that will be set along with the request

step to run in your computer:
python -m venv venv
.venv\scripts\activate
pip install requirements.txt

Use virtual env for both task

## Start the Playwright Driver server on one terminal
python -m src.drivers.grpc_playwright_server

On another sample
python -m src.agents.runner "change the task status of Schedule kickoff meeting to complete in asana"
python -m src.agents.runner "Create a new message to kgen4295@gmail.com to come early in the meeting in asana"
python -m src.agents.runner "logout from asana"


python -m src.agents.runner "create a new project called Softlight in linear"
python -m src.agents.runner "Write a new issue Make Web Agent B to project Softlight in linear and assign to kgen"
python -m src.agents.runner "change my name to kgen in linear"
python -m src.agents.runner "go to issues and filter by inprogress and change the status of clean up ui to done in linear"




https://drive.google.com/file/d/1R1ZWtm_hxvbwFmnLNKYsPBuPkYcuW8vg/view?usp=sharing
https://www.loom.com/share/84af53d90dab4ac5a8da97a27c83fbea
https://github.com/Khagendra01/Autonomous-Web-Agent

BenchMark across the model:
choosen GPT model
GPT-5 -> take way too long just process IO, maybe of compute time of large parameter or its instances still not deployed as much as 4o
gpt-5-mini -> does the task well however still slower
gpt-4o-> is medium level does but sometime hallucinate or lack intelligience of gpt-5
gpt-4o-mini-> bro looks like a boy in the war who mistake all the time

SO SELCECTED IS GPT 4.1 after so many testing.

Preferences -> Gpt4o/ 5-mini

## Custom Architecture designed by me

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

