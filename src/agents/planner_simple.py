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
        
        # ⚡ IMPROVEMENT 1: Prioritize "create" buttons and show more elements (up to 100)
        priority_elements = []
        regular_elements = []
        
        for item in interactables:
            label = (item.get('label') or '').lower()
            if any(word in label for word in ['create', 'new', 'add', '+']) or label == '+':
                priority_elements.append(item)
            else:
                regular_elements.append(item)
        
        # Show priority elements first, then regular, up to 100 total
        ordered_elements = priority_elements + regular_elements
        display_elements = ordered_elements[:100]
        
        elements_text = "\n".join([
            f"{i+1}. {item.get('role')} - \"{item.get('label', 'no label')}\" (selector: {item.get('selector')})"
            for i, item in enumerate(display_elements)
        ])
        
        if len(interactables) > 100:
            elements_text += f"\n... and {len(interactables) - 100} more elements"
        
        # ⚡ IMPROVEMENT 2: Detect infinite loops
        loop_warning = ""
        recent_actions = state.action_history[-5:] if len(state.action_history) >= 5 else []
        
        if len(recent_actions) >= 3:
            # Check if last 3 actions are identical
            if recent_actions[-1] == recent_actions[-2] == recent_actions[-3]:
                loop_warning = f"\n\n⚠️ LOOP DETECTED: You've repeated '{recent_actions[-1]}' 3+ times with no progress!\nTry a COMPLETELY DIFFERENT action - scroll to find new elements, or try a different button."
        
        # ⚡ IMPROVEMENT 3: Provide action result feedback
        action_result = ""
        if state.last_action_result:
            action_result = f"\nLAST ACTION RESULT: {state.last_action_result}"
        
        # Simple prompt - let LLM figure everything out
        prompt = f"""You are a web automation agent.

GOAL: {state.goal}
CURRENT URL: {state.current_url}
STEP: {state.step_count}/{state.max_steps}

AVAILABLE ELEMENTS ({len(display_elements)} shown, priority buttons listed first):
{elements_text if elements_text else "No elements found"}

LAST ACTION: {state.last_action or 'None'}{action_result}{loop_warning}

What should you do next? Choose from:
- click: Click an element (provide exact selector from list)
- type: Type text into an input (provide selector and text)
- scroll: Scroll the page to reveal more elements

IMPORTANT:
- If you see a loop warning, you MUST try something different (scroll or different button)
- Only use selectors EXACTLY as shown in the list above
- "Create" and "New" buttons are shown first to help you find them quickly

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

