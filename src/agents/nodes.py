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
        'errors': data.get('errors') or [],
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


# (Removed synthesis; LLM drives all actions.)

def _action_key_from_scored(action: ScoredAction) -> str:
    # Key prioritizes selector + type which best identifies a unique UI action
    return f"{action.action_type}|{action.selector}"

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
**Task**: Score each element from 0-10 based on how likely acting on it (click, type, or scroll) will help achieve the goal.
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
- If a textbox for the object's name is present (e.g., "Project name"), propose a `type` action with appropriate text extracted from the goal.
 - If relevant controls are likely off-screen (long lists, partial content, or no strong candidates), include a `scroll` candidate to discover elements. Use label "Scroll down" (delta ≈ +600) or "Scroll up" (delta ≈ -600) as appropriate. Use selector "window".

Return a JSON array with this structure:
[
  {{
    "selector": "role=button[name=\"Create project\"]",
    "label": "Create project",
    "action_type": "click",
    "score": 9.5,
    "reasoning": "This button directly opens the project creation flow"
  }},
  {{
    "selector": "role=textbox[name=\"Project name\"]",
    "label": "Project name",
    "action_type": "type",
    "text": "gamma",
    "score": 10,
    "reasoning": "Entering the required project name aligns with the goal"
  }},
  {{
    "selector": "window",
    "label": "Scroll down",
    "action_type": "scroll",
    "score": 6.5,
    "reasoning": "No high-confidence controls are visible; scroll to reveal more."
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

        # Deduplicate by action_type|selector key, keeping the highest-scored instance
        unique_by_key: Dict[str, ScoredAction] = {}
        for a in scored_actions:
            k = _action_key_from_scored(a)
            existing = unique_by_key.get(k)
            if existing is None or a.score > existing.score:
                unique_by_key[k] = a

        deduped: List[ScoredAction] = list(unique_by_key.values())

        # Sort by the LLM-provided score only (no heuristics)
        adjusted: List[ScoredAction] = sorted(deduped, key=lambda x: x.score, reverse=True)

        print(f"  Scored {len(adjusted)} actions (deduped)")
        # Show top 3 as a quick summary
        for i, action in enumerate(adjusted[:3]):
            print(f"  {i+1}. [{action.score:.1f}] {action.action_type} '{action.label}' - {action.reasoning}")

        # Also show the same-score group (within 1.0 of the top score)
        if adjusted:
            top_score = adjusted[0].score
            same_group = [a for a in adjusted if a.score >= top_score - 1.0][:8]
            if len(same_group) > 1:
                print("  Same-score group (±1.0 from top):")
                for a in same_group:
                    suffix = f" → type text='{a.text}'" if (a.action_type == 'type' and a.text) else ""
                    print(f"    - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix}")

        return {
            'scored_actions': adjusted,
            'next_action': None,  # selection is delegated to decide_action_node
        }
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse LLM response: {e}")
        print(f"  Raw response: {content[:200]}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Failed to parse LLM response: {e}"
        }
def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to choose the next action from scored candidates, considering goal, errors, and history."""
    print(f"\n[DECIDE] Selecting next action using LLM policy")

    scored = state.get('scored_actions') or []
    if not scored:
        return { 'next_action': state.get('next_action') }

    # Filter out actions already tried on this URL to avoid loops
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    filtered_scored: List[ScoredAction] = [a for a in scored if _action_key_from_scored(a) not in tried_here]
    if filtered_scored:
        if len(filtered_scored) != len(scored):
            print("  Skipping previously tried action(s) on this page; choosing next best candidate")
        base_list = filtered_scored
    else:
        # If we've exhausted options, fall back to full list to avoid stalling
        base_list = scored

    # Prepare compact candidate list for the prompt
    candidates = [
        {
            'i': i,
            'action_type': a.action_type,
            'label': a.label,
            'selector': a.selector,
            'score': a.score,
            'text': a.text,
            'reasoning': a.reasoning,
        }
        for i, a in enumerate(base_list[:12]) # cap to avoid token bloat
    ]

    recent = state['action_history'][-5:]
    errors = state.get('errors') or []

    prompt = f"""You are a decision policy that chooses the next UI action from candidates.

Goal: {state['goal']}
Current URL: {state['current_url']}
Errors/Validation: {json.dumps(errors)}

Recent actions (last 5): {json.dumps(recent)}

Candidates (choose one by index 'i'):
{json.dumps(candidates, indent=2)}

Guidelines:
- Prefer actions that directly advance the goal semantics (e.g., delete when goal mentions delete).
- If validation indicates required fields, prefer typing the missing value before submitting.
- If a modal/menu is open, prefer the confirm/primary/destructive action inside it rather than reopening the menu.
- Avoid repeating the exact same action unless necessary.
- Consider the provided scores but you may override them when context (goal/errors) dictates a better choice.
 - If none of the candidates clearly advance the goal and recent attempts stalled, prefer a brief exploratory `scroll` (down first, then up) to reveal additional controls before retrying similar clicks.

Return ONLY a JSON object in this shape:
{{
  "i": <candidate index>,
  "rationale": "why this is best",
  "textOverride": "optional text for type actions or null"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Select the best next action for goal-directed web automation. Return only valid JSON."},
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

    try:
        decision = json.loads(content)
        idx = int(decision.get('i', 0))
        rationale = decision.get('rationale') or ''
        text_override = decision.get('textOverride')

        if 0 <= idx < len(candidates):
            chosen = base_list[idx]
            # Apply optional text override if LLM provided it
            if chosen.action_type == 'type' and text_override is not None:
                chosen = ScoredAction(
                    action_type=chosen.action_type,
                    selector=chosen.selector,
                    label=chosen.label,
                    score=chosen.score,
                    reasoning=rationale or chosen.reasoning,
                    text=str(text_override),
                )
            else:
                chosen = ScoredAction(
                    action_type=chosen.action_type,
                    selector=chosen.selector,
                    label=chosen.label,
                    score=chosen.score,
                    reasoning=rationale or chosen.reasoning,
                    text=chosen.text,
                )

            print(f"  Chosen: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}'")
            print(f"  Policy rationale: {rationale}")
            return { 'next_action': chosen }

        # Fallback to previous heuristic choice
        return { 'next_action': state.get('next_action') }

    except Exception as e:
        print(f"  ⚠️  Failed to parse decision: {e}")
        return { 'next_action': state.get('next_action') }


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
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if action.selector and action.action_type in ('click', 'type'):
            crop_resp = requests.post(f"{DRIVER_URL}/screenshot_region", json={
                'selector': action.selector,
                'margin': 24,
            }, timeout=10)
            if crop_resp.status_code == 200 and crop_resp.content:
                # Append focused image to screenshots list
                focused_bytes = crop_resp.content
                screenshots = state.get('screenshots') or []
                screenshots = screenshots + [focused_bytes]
                # Track that this focused screenshot corresponds to the current step index
                focused_after_steps = set(state.get('focused_after_steps') or [])
                focused_after_steps.add(state.get('step_count', 0))
            else:
                screenshots = state.get('screenshots') or []
                focused_after_steps = set(state.get('focused_after_steps') or [])
        else:
            screenshots = state.get('screenshots') or []
            focused_after_steps = set(state.get('focused_after_steps') or [])
    except Exception:
        screenshots = state.get('screenshots') or []
        focused_after_steps = set(state.get('focused_after_steps') or [])

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
        
        # Record this action as tried for the current URL to avoid repeating it
        current_url = state.get('current_url') or ''
        tried_map = dict(state.get('tried_actions_by_url') or {})
        tried_here = list(tried_map.get(current_url, []))
        action_key = _action_key_from_scored(action)
        if action_key not in tried_here:
            tried_here.append(action_key)
        tried_map[current_url] = tried_here
        
        return {
            'action_history': state['action_history'] + [action_record],
            'step_count': state['step_count'] + 1,
            'stuck_count': 0,
            'tried_actions_by_url': tried_map,
            'screenshots': screenshots,
            'focused_after_steps': list(focused_after_steps),
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
    
    # Heuristic: if the goal is about commenting and we successfully typed then clicked 'Comment', treat as success
    goal_text = (state.get('goal') or '').lower()
    if any(keyword in goal_text for keyword in ["comment", "commenting", "post a comment"]):
        recent = state.get('action_history', [])[-5:]
        saw_type_into_comment = any(
            (a.get('type') == 'type' and 'comment' in (a.get('label') or '').lower())
            or (a.get('type') == 'type' and 'comment' in (a.get('selector') or '').lower())
            for a in recent
        )
        saw_click_comment = any(
            (a.get('type') == 'click' and 'comment' in (a.get('label') or '').lower())
            or (a.get('type') == 'click' and 'comment' in (a.get('selector') or '').lower())
            for a in recent
        )
        # If we executed both actions without an error flagged, assume success
        if saw_type_into_comment and saw_click_comment and not state.get('error'):
            print("  Goal reached: True (confidence: 1.0)")
            print("  Reasoning: Typed into the comment box and clicked the Comment button without errors; this satisfies the commenting goal.")
            return {
                'goal_reached': True
            }

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
    
    if state.get('stuck_count', 0) >= 2:
        print(f"\n⚠️  Agent appears stuck (failed actions: {state['stuck_count']})")
        return "end"
    
    # Do not end immediately on transient errors; keep going unless stuck/max_steps/goal.
    if state.get('error'):
        print(f"\n⚠️  Error encountered (continuing): {state['error']}")
        # Clear error so it doesn't spam subsequent iterations
        return "continue"
    
    return "continue"

