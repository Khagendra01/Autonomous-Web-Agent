from typing import Any, Dict, Optional, List
import json
import re

from ..state import AgentState
from .common import client
from ..utils.logger import get_logger


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        return None
    return None


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether the goal is complete using LLM with robust, app-agnostic criteria."""
    logger = get_logger()
    step = state.get('step_count', 0)
    logger.section(f"CHECK GOAL Step {step}")
    
    goal = state.get('goal', '')
    instruction = state.get('instruction', '')
    current_url = state.get('current_url', '')
    errors = state.get('errors', [])
    
    logger.info(f"Evaluating goal completion", {
        "goal": goal,
        "instruction": instruction,
        "current_url": current_url,
        "steps_taken": step,
        "errors": errors
    })

    # Quick heuristic check for logout success: if URL changed to login page and error says "logged out"
    goal_lower = (goal or instruction or '').lower()
    is_logout_task = 'logout' in goal_lower or 'log out' in goal_lower or 'sign out' in goal_lower
    url_is_login = '/login' in current_url or '/signin' in current_url or '/sign-in' in current_url
    has_logout_error = any('logged out' in str(err).lower() or 'log out' in str(err).lower() for err in errors)
    
    if is_logout_task and url_is_login and has_logout_error:
        logger.info("Quick heuristic: Logout detected via URL change and error message", {
            "url_changed_to_login": url_is_login,
            "logout_error_present": has_logout_error
        })
        logger.info("Goal reached: True (heuristic)", {
            "reasoning": f"URL changed to login page ({current_url}) and error message indicates logout successful",
            "confidence": 0.95
        })
        return {'goal_reached': True}
    
    model_name = state.get('llm_model') or "gpt-4.1"
    recent_actions = (state.get('action_history') or [])[-10:]

    # Normalize action details for evaluation
    action_details: List[Dict[str, Any]] = []
    for a in recent_actions:
        action_details.append({
            'type': a.get('type', ''),
            'label': a.get('label', ''),
            'text': a.get('text', ''),
            'score': a.get('score', 0),
            'reasoning': a.get('reasoning', ''),
        })

    last_action = action_details[-1] if action_details else None
    if last_action:
        text_part = f" with text '{last_action['text']}'" if last_action.get('text') else ""
        logger.info(f"Last action: {last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})")

    # Summarize interactable elements instead of including full list
    interactables = state.get('interactable_elements', [])
    interactable_summary = ""
    if interactables:
        # Count by role
        role_counts = {}
        for elem in interactables:
            role = elem.get('role', 'unknown')
            role_counts[role] = role_counts.get(role, 0) + 1
        
        # Find key elements that might indicate completion state
        key_elements = []
        for elem in interactables:
            label_lower = (elem.get('label', '') or '').lower()
            if any(keyword in label_lower for keyword in ['submit', 'create', 'save', 'confirm', 'done', 'complete', 'finish']):
                key_elements.append(f"{elem.get('role', 'unknown')}: '{elem.get('label', '')}'")
        
        interactable_summary = f"""
UI Summary:
- Total interactable elements: {len(interactables)}
- Elements by role: {json.dumps(role_counts, indent=2)}
- Key action buttons: {', '.join(key_elements[:10]) if key_elements else 'None found'}
"""
    else:
        interactable_summary = "\nUI Summary: No interactable elements detected."

    prompt = f"""Assess whether the user's goal has been completed based on the action history and current state.

Context:
- Goal: {state.get('goal', '')}
- Instruction: {state.get('instruction', '')}
- Current URL: {state.get('current_url', '')}
- Steps Taken: {state.get('step_count', 0)}
- Errors: {json.dumps(state.get('errors', []))}

Most recent action:
{json.dumps(last_action, indent=2) if last_action else "None"}

Complete Action History (chronological):
{json.dumps(action_details, indent=2)}
{interactable_summary}

Evaluation principles (generic, app-agnostic):
1) Favor completion when a coherent workflow of actions aligns with the goal and no errors are present.
2) If a visible submission/confirmation control remains (e.g., a generic submit/confirm control), prefer marking as incomplete.
3) Consider typed values matching goal parameters as strong evidence of progress/completion.
4) Avoid over-caution: many modern apps auto-save; absence of explicit submit does not always imply incompletion.
5) Provide a concise, evidence-based rationale referencing specific actions.

CRITICAL - Message/Form completion verification:
- For message creation tasks: verify that BOTH subject AND message body were typed. A message with only a subject but no body is INCOMPLETE.
- For form completion tasks: verify that ALL required fields were filled (recipient, subject/title, message body/description, etc.).
- Check the action history for "type" actions on message body fields (labels like "Edit message draft", "Message", "Body", "Description", etc.).
- If the goal requires sending a message and you only see typing actions for subject/recipient but NOT for message body, mark as INCOMPLETE.
- Example: If actions show "type on 'Add subject'" but no "type on 'Edit message draft'", the message body is missing - mark as incomplete.

Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "short evidence-based explanation",
  "confidence": 0.0-1.0,
  "missing_steps": ["optional list of next steps if not complete"]
}}"""

    try:
        logger.llm("Sending goal evaluation prompt to LLM", {"prompt_length": len(prompt)})
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You evaluate whether a web task is complete. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
        logger.llm("Received goal evaluation response", {"response_length": len(content)})
    except Exception as e:
        logger.error(f"Evaluation LLM call failed: {e}")
        return {'goal_reached': False}

    result = _extract_json_payload(content) or {}
    goal_reached = bool(result.get('goal_reached', False))
    reasoning = (result.get('reasoning') or 'Unknown').strip()
    try:
        confidence = float(result.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    missing_steps = result.get('missing_steps', []) or []

    logger.info("Goal evaluation result", {
        "goal_reached": goal_reached,
        "confidence": confidence,
        "reasoning": reasoning,
        "missing_steps": missing_steps
    })

    return { 'goal_reached': goal_reached }


