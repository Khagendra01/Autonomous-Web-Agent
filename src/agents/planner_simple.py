"""
Simplified Planner - Minimal LLM-based agent planning.

This version removes all the complexity and lets the LLM do the heavy lifting.
No special cases, no heuristics, just pure LLM reasoning.
"""

from typing import Dict
from .state import AgentState
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
import os
import json
from dotenv import load_dotenv

load_dotenv()


class SimplePlanner:
    def __init__(self):
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set. Please create a .env file with OPENAI_API_KEY=your_key")
        
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=api_key,
            temperature=0.0,
        )
    
    def extract_app_and_url(self, goal: str) -> Dict[str, str]:
        """Extract app name and URL from goal."""
        prompt = f"""Extract the web app and URL from this goal: "{goal}"

Common apps:
- Linear: https://linear.app/
- Notion: https://www.notion.so/
- GitHub: https://github.com/
- Gmail: https://mail.google.com/

Respond in JSON: {{"app": "app_name", "url": "https://..."}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            print(f"[LLM] App: {result['app']}, URL: {result['url']}")
            return result
            
        except Exception as e:
            print(f"[ERROR] Failed to extract app/URL: {e}")
            return {'app': 'unknown', 'url': 'https://www.google.com'}
    
    def plan_next_action(self, state: AgentState) -> AgentState:
        """Simple planning - just ask LLM what to do next."""
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        
        # Format available elements (keep it simple - just show first 20)
        elements_text = "\n".join([
            f"{i+1}. {item.get('role')} - \"{item.get('label', 'no label')}\" (selector: {item.get('selector')})"
            for i, item in enumerate(interactables[:20])
        ])
        
        if len(interactables) > 20:
            elements_text += f"\n... and {len(interactables) - 20} more elements"
        
        # Simple prompt - let LLM figure everything out
        prompt = f"""You are a web automation agent.

GOAL: {state.goal}
CURRENT URL: {state.current_url}
STEP: {state.step_count}/{state.max_steps}

AVAILABLE ELEMENTS:
{elements_text if elements_text else "No elements found"}

LAST ACTION: {state.last_action or 'None'}

What should you do next? Choose from:
- click: Click an element (provide exact selector from list)
- type: Type text into an input (provide selector and text)
- scroll: Scroll the page

Respond in JSON:
{{
  "reasoning": "why you chose this action",
  "action": {{
    "type": "click|type|scroll",
    "selector": "exact selector from list above",
    "text": "text to type (if type action)",
    "delta": 700
  }}
}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            state.reasoning = result.get('reasoning', '')
            state.next_action = result.get('action', {})
            
            print(f"[PLAN] {state.reasoning}")
            print(f"[ACTION] {state.next_action}")
            
        except Exception as e:
            print(f"[ERROR] Planning failed: {e}")
            # Fallback: scroll
            state.reasoning = f"Error: {e}"
            state.next_action = {'type': 'scroll', 'delta': 700}
        
        return state
    
    def check_completion(self, state: AgentState) -> AgentState:
        """Check if goal is achieved."""
        prompt = f"""Is this goal complete?

GOAL: {state.goal}
CURRENT URL: {state.current_url}
STEPS TAKEN: {state.step_count}
LAST ACTION: {state.last_action}

Respond in JSON:
{{
  "completed": true/false,
  "reasoning": "why you think it's complete or not"
}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            if result.get('completed', False):
                state.done = True
                state.success = True
                print(f"[SUCCESS] {result.get('reasoning')}")
            
        except Exception as e:
            print(f"[ERROR] Validation failed: {e}")
        
        return state

