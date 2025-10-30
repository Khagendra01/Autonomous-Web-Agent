"""
Flood Fill Planner - Uses State Space Graph for autonomous exploration.

Like Micromouse:
- Explores the UI "maze"
- Calculates distances using flood fill
- Always moves toward lowest distance neighbor
- Learns optimal paths automatically
"""

from typing import Dict, List, Optional
from .state import AgentState
from .state_graph import StateGraph
from .utils.dom import dom_fingerprint, summarize_accessibility_tree
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
import os
import json
from dotenv import load_dotenv

load_dotenv()


class FloodFillPlanner:
    def __init__(self, app_name: str, graph_dir: str = "knowledge/graphs"):
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=api_key,
            temperature=0.0,
        )
        
        # Load or create state graph
        self.graph = StateGraph.load(app_name, graph_dir)
        if not self.graph:
            self.graph = StateGraph(app_name=app_name)
            print(f"[FLOOD FILL] Created new state graph for {app_name}")
        else:
            print(f"[FLOOD FILL] Loaded existing graph with {len(self.graph.states)} states")
        
        self.graph_dir = graph_dir
    
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
    
    def update_state_graph(self, state: AgentState):
        """Update state graph with current observation."""
        obs = state.observation or {}
        a11y = obs.get('a11y', {})
        a11y_str = summarize_accessibility_tree(a11y)
        fingerprint = dom_fingerprint(a11y_str)
        
        state.current_fingerprint = fingerprint
        
        # Add current state to graph
        elements_count = len(obs.get('interactables', []))
        current_ui_state = self.graph.add_state(
            fingerprint=fingerprint,
            url=state.current_url or '',
            elements_count=elements_count
        )
        
        # Add transition from last state if action was taken
        if state.last_fingerprint and state.last_action:
            action_parts = state.last_action.split(':')
            action_type = action_parts[0] if len(action_parts) > 0 else 'unknown'
            
            # Extract selector and text from next_action if available
            last_action_data = state.next_action or {}
            selector = last_action_data.get('selector')
            text = last_action_data.get('text')
            
            success = '✓' in (state.last_action_result or '')
            
            self.graph.add_transition(
                from_fingerprint=state.last_fingerprint,
                to_fingerprint=fingerprint,
                action_type=action_type,
                selector=selector,
                text=text,
                success=success
            )
        
        # Save fingerprint for next transition
        state.last_fingerprint = fingerprint
        
        return current_ui_state
    
    def check_if_goal(self, state: AgentState) -> bool:
        """Use LLM to check if current state achieved the goal."""
        
        # Get current page elements for verification
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        elements_text = ', '.join([f"\"{item.get('label')}\"" for item in interactables[:30]])
        
        prompt = f"""Has this goal been FULLY achieved and COMPLETED?

GOAL: {state.goal}
CURRENT URL: {state.current_url}
STEPS TAKEN: {state.step_count}

Recent actions:
{self._format_recent_actions(state)}

CURRENT PAGE ELEMENTS:
{elements_text}

IMPORTANT: 
- Goal is achieved ONLY if the task is FULLY COMPLETE
- For "create X named Y": The item must EXIST and be visible, not just typed in a form
- Typing in a form is NOT completion - the form must be SUBMITTED
- If you see a submit/create button that hasn't been clicked, goal is NOT achieved
- Look for evidence the item was created (success message, item appears in list, etc.)

Respond in JSON:
{{
  "achieved": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "concrete evidence (or lack of) that goal is complete"
}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            # Require high confidence (0.8+) to avoid false positives
            if result.get('achieved', False) and result.get('confidence', 0) >= 0.8:
                print(f"[GOAL] ✅ Achieved! {result.get('reasoning')}")
                
                # Mark current state as goal and run flood fill
                if state.current_fingerprint:
                    self.graph.set_goal_state(state.current_fingerprint)
                
                return True
            
            # Log if close but not quite there
            if result.get('confidence', 0) >= 0.5:
                print(f"[GOAL] Not yet complete: {result.get('reasoning')}")
            
            return False
            
        except Exception as e:
            print(f"[ERROR] Goal check failed: {e}")
            return False
    
    def estimate_goal_distance(self, state: AgentState) -> float:
        """Use LLM to estimate how close current state is to goal (0=goal, 1=far)."""
        prompt = f"""How close is this state to achieving the goal?

GOAL: {state.goal}
CURRENT URL: {state.current_url}

Rate closeness from 0.0 (goal achieved) to 1.0 (very far from goal).

Examples:
- On goal page with task complete: 0.0
- On goal page but task not done: 0.3
- On relevant section: 0.5
- On irrelevant page: 0.9

Respond in JSON:
{{
  "distance": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            distance = result.get('distance', 0.5)
            
            # Update current state's goal score
            if state.current_fingerprint and state.current_fingerprint in self.graph.states:
                self.graph.states[state.current_fingerprint].goal_score = distance
            
            return distance
            
        except Exception as e:
            print(f"[ERROR] Distance estimation failed: {e}")
            return 0.5  # Default: medium distance
    
    def _format_recent_actions(self, state: AgentState) -> str:
        """Format recent action logs for LLM."""
        logs = state.memory.action_logs[-5:]
        if not logs:
            return "No actions yet"
        
        lines = []
        for log in logs:
            lines.append(f"  Step {log.step}: {log.action} → {log.result}")
        return "\n".join(lines)
    
    def plan_next_action(self, state: AgentState) -> AgentState:
        """
        Plan next action using Flood Fill strategy:
        1. Check if we know good path (exploit)
        2. If not, explore new actions
        3. Always prefer actions leading to lowest distance
        """
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        
        # Update state graph with current observation
        current_ui_state = self.update_state_graph(state)
        
        print(f"[FLOOD FILL] State: {current_ui_state.fingerprint[:12]}... "
              f"(visited {current_ui_state.visited_count}x, distance={current_ui_state.distance_to_goal:.1f})")
        
        # Strategy 1: If we have known transitions, use best one (EXPLOIT)
        best_known_action = current_ui_state.get_best_action(self.graph)
        
        if best_known_action and best_known_action[1].success_rate > 0.5:
            action_key, transition = best_known_action
            
            print(f"[STRATEGY] EXPLOIT known path (success rate: {transition.success_rate:.0%})")
            
            state.reasoning = f"Following known good path: {action_key}"
            state.next_action = {
                'type': transition.action_type,
                'selector': transition.action_selector,
                'text': transition.action_text,
                'delta': 700
            }
            
            print(f"[PLAN] {state.reasoning}")
            print(f"[ACTION] {state.next_action}")
            
            return state
        
        # Strategy 2: Explore new actions (EXPLORE)
        print(f"[STRATEGY] EXPLORE new actions")
        
        # Get unexplored actions
        available_actions = [
            {
                'role': item.get('role'),
                'label': item.get('label'),
                'selector': item.get('selector')
            }
            for item in interactables
        ]
        
        unexplored = self.graph.get_unexplored_actions(current_ui_state, available_actions)
        
        if unexplored:
            print(f"[EXPLORE] Found {len(unexplored)} unexplored actions")
            
            # Use LLM to pick best unexplored action (pure reasoning, no rules)
            state = self._llm_explore(state, unexplored)
        else:
            # All actions explored, scroll or retry
            print(f"[EXPLORE] All actions tried, scrolling...")
            state.reasoning = "All actions explored, scrolling to find more"
            state.next_action = {'type': 'scroll', 'delta': 700}
        
        print(f"[PLAN] {state.reasoning}")
        print(f"[ACTION] {state.next_action}")
        
        return state
    
    def _llm_explore(self, state: AgentState, unexplored_actions: List[Dict]) -> AgentState:
        """Use LLM to choose best action from unexplored options - pure reasoning, no rules."""
        
        # Get current state for context
        current_ui_state = self.graph.states.get(state.current_fingerprint)
        
        # Simply group by type for clear presentation (no prioritization)
        by_type = {}
        for act in unexplored_actions:
            role = act.get('role', 'unknown')
            if role not in by_type:
                by_type[role] = []
            by_type[role].append(act)
        
        # Format elements grouped by type
        actions_parts = []
        counter = 1
        
        # Logical order: textboxes, buttons, links, others (neutral, no priorities)
        type_order = ['textbox', 'combobox', 'button', 'link', 'menuitem', 'checkbox', 'radio']
        
        for role in type_order:
            if role in by_type:
                items = by_type[role][:50]  # Show up to 50 of each type
                actions_parts.append(f"\n{role.upper()}S ({len(items)}):")
                for act in items:
                    label = act.get('label', 'no label')
                    selector = act.get('selector', 'no selector')
                    actions_parts.append(f"  [{counter}] \"{label}\" → {selector}")
                    counter += 1
        
        # Add remaining types
        for role, items in by_type.items():
            if role not in type_order:
                actions_parts.append(f"\n{role.upper()}S ({len(items)}):")
                for act in items[:20]:
                    label = act.get('label', 'no label')
                    selector = act.get('selector', 'no selector')
                    actions_parts.append(f"  [{counter}] \"{label}\" → {selector}")
                    counter += 1
        
        actions_text = "\n".join(actions_parts)
        
        # Simple, neutral prompt - let LLM reason
        prompt = f"""You are autonomously exploring a web UI to achieve: {state.goal}

Current page: {state.current_url}
Distance estimate: {self.graph.states[state.current_fingerprint].distance_to_goal:.1f}

UNEXPLORED ELEMENTS:{actions_text}

CONTEXT:
- You've tried {len(current_ui_state.transitions) if current_ui_state else 0} actions from this state before
- Recent actions: {', '.join(state.action_history[-3:]) if state.action_history else 'None'}

Think step-by-step:
1. What elements are relevant to my goal?
2. What's the logical next step in this workflow?
3. If I see form fields, should I fill them? If so, extract values from goal.
4. Should I click a button to navigate or submit?

Choose the MOST RELEVANT action to progress toward the goal.

Respond in JSON:
{{
  "reasoning": "your step-by-step thinking",
  "action": {{"type": "click|type|scroll", "selector": "exact selector", "text": "if typing, extract from goal"}}
}}"""

        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            content = response.content
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            state.reasoning = result.get('reasoning', 'Exploring new action')
            state.next_action = result.get('action', {'type': 'scroll', 'delta': 700})
            
        except Exception as e:
            print(f"[ERROR] LLM exploration failed: {e}")
            # Fallback: pick first unexplored action
            if unexplored_actions:
                first = unexplored_actions[0]
                state.reasoning = f"Trying unexplored: {first.get('label')}"
                state.next_action = {
                    'type': 'click',
                    'selector': first.get('selector')
                }
            else:
                state.reasoning = "Scrolling"
                state.next_action = {'type': 'scroll', 'delta': 700}
        
        return state
    
    def save_graph(self):
        """Save state graph to disk."""
        self.graph.save(self.graph_dir)
        stats = self.graph.get_statistics()
        print(f"[GRAPH STATS] States: {stats['total_states']}, "
              f"Transitions: {stats['total_transitions']}, "
              f"Goals: {stats['goal_states']}")

