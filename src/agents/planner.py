from typing import Dict, Any
from .state import AgentState
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Planner:
    def __init__(self):
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set. Please create a .env file with OPENAI_API_KEY=your_key")
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=api_key,
            temperature=0.0,
        )

    def reason_and_plan(self, state: AgentState) -> AgentState:
        """Use LLM to reason about current state and plan next action."""
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        errors = obs.get('errors', [])
        
        # Format interactables for LLM
        interactables_text = "\n".join([
            f"- {i+1}. {act.get('role', 'unknown')} - \"{act.get('label', 'no label')}\" (selector: {act.get('selector', 'N/A')})"
            for i, act in enumerate(interactables[:30])  # Limit to first 30
        ])
        
        # Format errors
        errors_text = "\n".join([f"- {err}" for err in errors]) if errors else "None"
        
        system_prompt = """You are a web automation agent. Your job is to:
1. Analyze the current state of the webpage
2. Reason about what needs to be done to achieve the goal
3. Decide on the next best action

IMPORTANT: If you see error messages or validation failures, you MUST adapt your strategy:
- If a name/URL is already taken, try a different one (add suffix, use timestamp, etc.)
- If an action failed, try a different approach
- Learn from errors and don't repeat the same failing action

You can perform these actions:
- click: Click on an element (requires selector)
- type: Type text into an input field (requires selector and text)
- scroll: Scroll the page (optional delta in pixels)

Respond in JSON format:
{
  "reasoning": "Your analysis of the current situation, including any errors",
  "current_step": "What you're trying to accomplish right now",
  "action": {
    "type": "click|type|scroll",
    "selector": "role=button[name='...']",
    "text": "text to type (if type action)",
    "delta": 700,
    "intent": "brief description of why"
  }
}"""

        user_prompt = f"""Goal: {state.goal}
Current URL: {state.current_url}
Step count: {state.step_count}/{state.max_steps}

Last action: {state.last_action or 'None'}
Last action result: {state.last_action_result or 'Unknown'}

Recent actions: {', '.join(state.action_history[-5:]) if state.action_history else 'None yet'}

ERROR MESSAGES on page:
{errors_text}

Available interactive elements on the page:
{interactables_text if interactables_text else "No clear interactive elements found"}

What should I do next to achieve the goal? If there are errors, adapt your approach accordingly."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            
            # Parse JSON from response
            if isinstance(content, str):
                # Try to extract JSON from markdown code blocks if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                result = json.loads(content)
            else:
                result = content
            
            state.reasoning = result.get('reasoning', '')
            state.current_step = result.get('current_step', '')
            state.next_action = result.get('action', {})
            
        except Exception as e:
            print(f"[ERROR] LLM planning failed: {e}")
            # Fallback: scroll
            state.reasoning = f"Error in LLM call: {e}"
            state.current_step = "Exploring page"
            state.next_action = {'type': 'scroll', 'delta': 700, 'intent': 'explore'}
        
        return state

    def validate_completion(self, state: AgentState) -> AgentState:
        """Use LLM to determine if the goal has been achieved."""
        obs = state.observation or {}
        hint = obs.get('hint', '')
        
        system_prompt = """You are validating if a web automation goal has been completed.
Analyze the current state and determine if the goal has been successfully achieved.

Respond in JSON format:
{
  "completed": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "Why you think it's complete or not",
  "success": true/false
}"""

        user_prompt = f"""Goal: {state.goal}
Current URL: {state.current_url}
Steps taken: {state.step_count}
Last action: {state.last_action}
Recent actions: {', '.join(state.action_history[-5:]) if state.action_history else 'None'}
Hint from page: {hint}

Has the goal been achieved? Is the task complete?"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            
            if isinstance(content, str):
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                result = json.loads(content)
            else:
                result = content
            
            if result.get('completed', False) and result.get('confidence', 0) > 0.7:
                state.done = True
                state.success = result.get('success', True)
                print(f"[SUCCESS] Goal achieved! Reasoning: {result.get('reasoning')}")
            
        except Exception as e:
            print(f"[ERROR] Validation failed: {e}")
        
        return state

