from typing import Any, Dict, Optional, List
import json
import re

from ..state import AgentState
from .common import client


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
    print(f"\n[CHECK GOAL] Evaluating goal completion")
    print(f"  Goal: {state.get('goal', '')}")
    print(f"  Steps taken: {state.get('step_count', 0)}")

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
        print(f"  Last action: {last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})")

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

Currently Available UI Elements (if any):
{json.dumps(state.get('interactable_elements', []), indent=2)}

Evaluation principles (generic, app-agnostic):
1) Favor completion when a coherent workflow of actions aligns with the goal and no errors are present.
2) If a visible submission/confirmation control remains (e.g., a generic submit/confirm control), prefer marking as incomplete.
3) Consider typed values matching goal parameters as strong evidence of progress/completion.
4) Avoid over-caution: many modern apps auto-save; absence of explicit submit does not always imply incompletion.
5) Provide a concise, evidence-based rationale referencing specific actions.

Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "short evidence-based explanation",
  "confidence": 0.0-1.0,
  "missing_steps": ["optional list of next steps if not complete"]
}}"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You evaluate whether a web task is complete. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  Evaluation LLM call failed: {e}")
        return {'goal_reached': False}

    result = _extract_json_payload(content) or {}
    goal_reached = bool(result.get('goal_reached', False))
    reasoning = (result.get('reasoning') or 'Unknown').strip()
    try:
        confidence = float(result.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    missing_steps = result.get('missing_steps', []) or []

    print(f"  Goal reached: {goal_reached} (confidence: {confidence:.1%})")
    if reasoning:
        print(f"  Reasoning: {reasoning}")
    if missing_steps:
        try:
            print(f"  Missing steps: {', '.join(map(str, missing_steps))}")
        except Exception:
            print("  Missing steps: (unprintable)")

    return { 'goal_reached': goal_reached }


