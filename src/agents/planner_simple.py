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
        """Simple planning - just give LLM complete context and let it think."""
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        
        # Group elements by type for clear structure
        by_type = {}
        for item in interactables:
            role = item.get('role', 'unknown')
            if role not in by_type:
                by_type[role] = []
            by_type[role].append(item)
        
        # Format elements grouped by type (show up to 100)
        elements_parts = []
        total_shown = 0
        
        # Show in logical order: textboxes, buttons, links, others
        priority_order = ['textbox', 'combobox', 'button', 'link', 'menuitem', 'checkbox', 'radio']
        
        for role in priority_order:
            if role in by_type and total_shown < 100:
                items = by_type[role][:100 - total_shown]
                elements_parts.append(f"\n{role.upper()}S ({len(items)}):")
                for item in items:
                    total_shown += 1
                    label = item.get('label', 'no label')
                    elements_parts.append(f"  [{total_shown}] \"{label}\" → {item.get('selector')}")
        
        # Add remaining types
        for role, items in by_type.items():
            if role not in priority_order and total_shown < 100:
                items_to_show = items[:100 - total_shown]
                elements_parts.append(f"\n{role.upper()}S ({len(items)}):")
                for item in items_to_show:
                    total_shown += 1
                    label = item.get('label', 'no label')
                    elements_parts.append(f"  [{total_shown}] \"{label}\" → {item.get('selector')}")
        
        elements_text = "\n".join(elements_parts)
        
        if len(interactables) > 100:
            elements_text += f"\n\n(+{len(interactables) - 100} more elements not shown)"
        
        # Build rich context from action logs
        recent_context = ""
        logs = state.memory.action_logs[-5:]  # Last 5 actions
        
        if logs:
            recent_context = "\n\nRECENT ACTIONS YOU TOOK:"
            for log in logs:
                recent_context += f"\n  Step {log.step}: {log.action} → {log.result}"
                # Show intent only if different from action
                if log.intent and log.intent != "No reasoning provided":
                    intent_short = log.intent[:80] + "..." if len(log.intent) > 80 else log.intent
                    recent_context += f"\n    Why: {intent_short}"
            
            # Check for loops
            if len(logs) >= 3:
                last_actions = [log.action for log in logs[-3:]]
                if last_actions[0] == last_actions[1] == last_actions[2]:
                    recent_context += "\n\n⚠️ You're repeating the same action - try something different!"
        
        # Minimal, clear prompt - let GPT-4o reason
        prompt = f"""You are automating: {state.goal}

Current page: {state.current_url}
Step: {state.step_count}/{state.max_steps}

AVAILABLE ELEMENTS:{elements_text}
{recent_context}

Actions:
- click: Click a button/link (use exact selector)
- type: Type into a textbox (use exact selector + text from goal)
- scroll: Scroll to see more (delta: pixels)

Think step-by-step:
1. Review what I've already accomplished (check recent actions above)
2. What's the next step in the workflow?
3. If I filled form fields, should I now submit?
4. If I keep repeating actions, am I stuck?

Respond in JSON:
{{
  "reasoning": "what I've done so far and what to do next",
  "action": {{"type": "click|type|scroll", "selector": "exact selector", "text": "if typing", "delta": 700}}
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

