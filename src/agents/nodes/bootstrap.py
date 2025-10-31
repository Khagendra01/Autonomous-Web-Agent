from typing import Any, Dict, List, Optional, Tuple
import json
import requests
import re

from ..state import AgentState
from .common import client, driver_client
from ..utils.logger import get_logger


def _parse_multiple_goals(instruction: str) -> Tuple[Optional[List[str]], str]:
    """
    Parse instruction to detect multiple sequential goals.
    Returns (multiple_goals_list, first_goal) if multiple goals detected, else (None, instruction).
    
    Example: "go to issues and filter by inprogress and change the status of clean up ui to done in linear"
    -> (["go to issues", "filter by inprogress", "change the status of clean up ui to done in linear"], "go to issues")
    """
    # Simple heuristic: split by " and " that appear to separate sequential actions
    # We'll look for patterns like "action1 and action2 and action3"
    # Split by " and " with spaces to avoid splitting within phrases
    parts = re.split(r'\s+and\s+', instruction, flags=re.IGNORECASE)
    
    # If we only have one part, no multiple goals
    if len(parts) <= 1:
        return None, instruction
    
    # Filter out very short parts (likely false positives from splitting)
    meaningful_parts = [p.strip() for p in parts if len(p.strip()) > 5]
    
    # If we have 2+ meaningful parts, treat as multiple goals
    if len(meaningful_parts) >= 2:
        return meaningful_parts, meaningful_parts[0]
    
    return None, instruction


def bootstrap_node(state: AgentState) -> Dict[str, Any]:
    """Infer base URL and app from instruction, init driver, and set goal.

    This enables instruction-only runs without explicit goal/URL flags.
    """
    logger = get_logger()
    
    instruction = state.get('instruction') or state.get('goal') or ''
    logger.info(f"\n[BOOTSTRAP] Inferring app and base URL from instruction: '{instruction}'")
    
    # Parse multiple sequential goals if present
    multiple_goals, first_goal = _parse_multiple_goals(instruction)
    if multiple_goals:
        logger.info(f"[BOOTSTRAP] Detected {len(multiple_goals)} sequential goals:")
        for i, goal in enumerate(multiple_goals, 1):
            logger.info(f"  {i}. {goal}")
        logger.info(f"[BOOTSTRAP] Starting with first goal: '{first_goal}'")
        # Use first goal for app/URL inference
        instruction_for_inference = first_goal
    else:
        instruction_for_inference = instruction

    prompt = f"""Given the user's instruction, infer the most likely web application and base URL to start from.

Instruction: "{instruction_for_inference}"

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
        ]
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    app_name = ""
    base_url = ""
    normalized_goal = instruction_for_inference
    try:
        parsed = json.loads(content)
        app_name = parsed.get('app_name') or ""
        base_url = parsed.get('base_url') or ""
        normalized_goal = parsed.get('normalized_goal') or instruction_for_inference
    except Exception:
        pass

    if not base_url:
        raise RuntimeError("Failed to infer base URL from instruction. Please specify a URL.")

    # Initialize driver at inferred base URL (gRPC)
    try:
        r = driver_client.init(app_name or 'WebApp', base_url)
        if not r.ok:
            raise RuntimeError(r.error or 'Driver init failed')
        logger.info(f"  ✓ Driver initialized at {base_url}")
    except Exception as e:
        logger.error(f"  ❌ Driver init error: {e}")
        return { 'error': str(e) }

    # Prepare return values
    result = {
        'goal': normalized_goal if not multiple_goals else first_goal,
        'app_name': app_name or 'WebApp',
        'base_url': base_url,
        'current_url': base_url,
    }
    
    # Add multiple goal tracking if multiple goals were detected
    if multiple_goals:
        result['multiple_goal'] = multiple_goals
        result['current_goal'] = first_goal
    else:
        result['multiple_goal'] = None
        result['current_goal'] = None
    
    return result


