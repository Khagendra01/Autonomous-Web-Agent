"""LangGraph nodes for the autonomous web agent."""
from typing import Any, Dict, List
import json
import requests
from openai import OpenAI
from .state import AgentState, ScoredAction
from .utils.dom import summarize_accessibility_tree
from dotenv import load_dotenv

# Load environment variables from .env (if present) before initializing OpenAI
load_dotenv()

# Initialize OpenAI client (reads OPENAI_API_KEY from env)
client = OpenAI()

# Driver API base URL
DRIVER_URL = "http://127.0.0.1:3999"


def bootstrap_node(state: AgentState) -> Dict[str, Any]:
    """Infer base URL and app from instruction, init driver, and set goal.

    This enables instruction-only runs without explicit goal/URL flags.
    """
    instruction = state.get('instruction') or state.get('goal') or ''
    print(f"\n[BOOTSTRAP] Inferring app and base URL from instruction: '{instruction}'")

    prompt = f"""Given the user's instruction, infer the most likely web application and base URL to start from.

Instruction: "{instruction}"

Return ONLY a JSON object with:
{{
  "app_name": "Readable app name, e.g., Linear, Notion, GitHub",
  "base_url": "Canonical login/home URL, e.g., https://linear.app, https://www.notion.so/",
  "normalized_goal": "A concise restatement of the user's goal"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Infer target app and base URL for web automation. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    app_name = ""
    base_url = ""
    normalized_goal = instruction
    try:
        parsed = json.loads(content)
        app_name = parsed.get('app_name') or ""
        base_url = parsed.get('base_url') or ""
        normalized_goal = parsed.get('normalized_goal') or instruction
    except Exception:
        pass

    if not base_url:
        raise RuntimeError("Failed to infer base URL from instruction. Please specify a URL.")

    # Initialize driver at inferred base URL
    try:
        resp = requests.post(f"{DRIVER_URL}/init", json={
            'app': app_name or 'WebApp',
            'url': base_url,
        }, timeout=30)
        rj = resp.json()
        if not rj.get('ok'):
            raise RuntimeError(rj.get('error') or 'Driver init failed')
        print(f"  ✓ Driver initialized at {base_url}")
    except Exception as e:
        print(f"  ❌ Driver init error: {e}")
        return { 'error': str(e) }

    return {
        'goal': normalized_goal,
        'app_name': app_name or 'WebApp',
        'base_url': base_url,
        'current_url': base_url,
    }


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    print(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state
    resp = requests.post(f"{DRIVER_URL}/observe")
    data = resp.json()
    
    # Capture screenshot
    screenshot_resp = requests.get(f"{DRIVER_URL}/screenshot")
    screenshot_bytes = screenshot_resp.content
    
    # Update state
    updates = {
        'current_url': data['url'],
        'dom_snapshot': data['a11y'],
        'interactable_elements': data['interactables'],
        'driver_hint': data.get('hint') or '',
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    print(f"  URL: {data['url']}")
    print(f"  Found {len(data['interactables'])} interactable elements")
    if data.get('errors'):
        print(f"  ⚠️  Errors detected: {data['errors']}")
    if updates['driver_hint']:
        print(f"  Hint: {updates['driver_hint']}")
    
    return updates


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions will lead to the goal."""
    print(f"\n[SCORE] Analyzing actions for goal: {state['goal']}")
    
    # Prepare context for LLM
    dom_summary = summarize_accessibility_tree(state['dom_snapshot'] or {})
    interactables = state['interactable_elements']  # Limit to avoid token overflow
    
    # Build action history summary
    history_summary = []
    for i, action in enumerate(state['action_history'][-5:]):  # Last 5 actions
        history_summary.append(f"{i+1}. {action['type']} on '{action.get('label', 'N/A')}'")
    
    prompt = f"""You are helping navigate a web application to achieve a goal.

**Goal**: {state['goal']}
**Current URL**: {state['current_url']}
**App**: {state['app_name']}

**Recent Actions**:
{chr(10).join(history_summary) if history_summary else "None yet"}

**Available Interactive Elements**:
{json.dumps(interactables, indent=2)}

"""
    # If driver provided a hint (e.g., found buttons containing create/new/add), surface it to the LLM
    if state.get('driver_hint'):
        prompt += f"""
Driver hint: {state['driver_hint']}
Prefer elements related to this hint if they advance the goal.
"""

    prompt += f"""
**Task**: Score each element from 0-10 based on how likely clicking it will help achieve the goal.
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Might be useful
- 0-3 = Unlikely to help or wrong direction

Also consider:
- Don't repeat recent actions unless necessary
- Look for buttons/links with relevant text (e.g., "Create", "New", "Filter", "Add")
- If we're in a modal/form, look for "Save", "Submit", "Create" buttons
- If stuck, try different approaches
- If the goal mentions an object (e.g., "project"), prefer actions that explicitly reference that object (e.g., "Add project", "New project", "Create project").

Return a JSON array with this structure:
[
  {{
    "selector": "role=button[name=\\"Create project\\"]",
    "label": "Create project",
    "action_type": "click",
    "score": 9.5,
    "reasoning": "This button directly opens the project creation flow"
  }},
  ...
]

Return ONLY the JSON array, no additional text."""

    # Call OpenAI
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at web navigation and UI analysis. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    
    # Parse response
    content = response.choices[0].message.content.strip()
    # Remove markdown code blocks if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    
    try:
        scored_actions_raw = json.loads(content)
        scored_actions = [
            ScoredAction(
                action_type=a['action_type'],
                selector=a['selector'],
                label=a['label'],
                score=float(a['score']),
                reasoning=a['reasoning'],
                text=a.get('text')
            )
            for a in scored_actions_raw
        ]
        
        # Heuristic re-ranking to reduce loops and prioritize goal-relevant CTAs
        goal_lower = (state.get('goal') or '').lower()
        last_selector = state['action_history'][-1]['selector'] if state['action_history'] else None

        adjusted: List[ScoredAction] = []
        for a in scored_actions:
            bonus = 0.0
            label_lower = (a.label or '').lower()
            # Prefer Add/New/Create + goal noun (e.g., project)
            if any(k in label_lower for k in ['add', 'new', 'create']) and any(obj in goal_lower for obj in ['project', 'issue', 'task', 'page']):
                if 'project' in goal_lower and 'project' in label_lower:
                    bonus += 3.0
                else:
                    bonus += 2.0
            # Penalize immediate repetition of the exact same selector
            if last_selector and a.selector == last_selector:
                bonus -= 2.5
            adjusted.append(ScoredAction(
                action_type=a.action_type,
                selector=a.selector,
                label=a.label,
                score=a.score + bonus,
                reasoning=a.reasoning,
                text=a.text,
            ))

        # Sort by adjusted score (highest first)
        adjusted.sort(key=lambda x: x.score, reverse=True)

        # Choose the top non-repeated action if available
        next_action = None
        for cand in adjusted:
            if not last_selector or cand.selector != last_selector:
                next_action = cand
                break
        if next_action is None and adjusted:
            next_action = adjusted[0]

        print(f"  Scored {len(adjusted)} actions")
        for i, action in enumerate(adjusted[:3]):
            print(f"  {i+1}. [{action.score:.1f}] {action.action_type} '{action.label}' - {action.reasoning}")

        return {
            'scored_actions': adjusted,
            'next_action': next_action,
        }
        
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse LLM response: {e}")
        print(f"  Raw response: {content[:200]}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Failed to parse LLM response: {e}"
        }


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    action = state['next_action']
    
    if not action:
        print(f"\n[EXECUTE] No action to execute")
        return {'error': 'No valid action found'}
    
    print(f"\n[EXECUTE] {action.action_type} on '{action.label}' (score: {action.score:.1f})")
    print(f"  Reasoning: {action.reasoning}")
    
    # Build action payload
    payload = {
        'type': action.action_type,
        'selector': action.selector,
    }
    
    if action.action_type == 'type' and action.text:
        payload['text'] = action.text
    
    # Execute via driver
    try:
        resp = requests.post(f"{DRIVER_URL}/act", json=payload, timeout=15)
        result = resp.json()
        
        if not result.get('ok'):
            print(f"  ❌ Action failed: {result.get('error')}")
            return {
                'error': result.get('error'),
                'stuck_count': state['stuck_count'] + 1
            }
        
        print(f"  ✓ Action executed successfully")
        
        # Add to history
        action_record = {
            'type': action.action_type,
            'selector': action.selector,
            'label': action.label,
            'score': action.score,
            'reasoning': action.reasoning,
        }
        
        return {
            'action_history': state['action_history'] + [action_record],
            'step_count': state['step_count'] + 1,
            'stuck_count': 0,
        }
        
    except Exception as e:
        print(f"  ❌ Exception during action: {e}")
        return {
            'error': str(e),
            'stuck_count': state['stuck_count'] + 1
        }


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to check if we've reached the goal."""
    print(f"\n[CHECK GOAL] Evaluating if goal is reached...")
    
    # Build context
    recent_actions = state['action_history'][-3:]
    action_summary = [f"{a['type']} on '{a['label']}'" for a in recent_actions]
    
    prompt = f"""Determine if the goal has been achieved based on the current state.

**Goal**: {state['goal']}
**Current URL**: {state['current_url']}
**Recent Actions**: {', '.join(action_summary) if action_summary else 'None'}
**Steps Taken**: {state['step_count']}

Has the goal been achieved? Consider:
- Did we complete the main action? (e.g., created a project, opened a filter)
- Are we in a success state or confirmation screen?
- Did we capture the key UI states needed for this workflow?

Respond with ONLY a JSON object:
{{
  "goal_reached": true/false,
  "reasoning": "Explanation of why the goal is/isn't reached",
  "confidence": 0.0-1.0
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at evaluating task completion. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    
    try:
        result = json.loads(content)
        goal_reached = result.get('goal_reached', False)
        reasoning = result.get('reasoning', 'Unknown')
        confidence = result.get('confidence', 0.5)
        
        print(f"  Goal reached: {goal_reached} (confidence: {confidence:.1%})")
        print(f"  Reasoning: {reasoning}")
        
        return {
            'goal_reached': goal_reached
        }
        
    except json.JSONDecodeError:
        print(f"  ⚠️  Failed to parse goal check response")
        return {'goal_reached': False}


def should_continue(state: AgentState) -> str:
    """Routing function to decide next step."""
    # Check stopping conditions
    if state.get('goal_reached'):
        return "end"
    
    if state['step_count'] >= state['max_steps']:
        print(f"\n⚠️  Max steps ({state['max_steps']}) reached")
        return "end"
    
    if state.get('stuck_count', 0) >= 3:
        print(f"\n⚠️  Agent appears stuck (failed actions: {state['stuck_count']})")
        return "end"
    
    if state.get('error'):
        print(f"\n⚠️  Error encountered: {state['error']}")
        return "end"
    
    return "continue"

