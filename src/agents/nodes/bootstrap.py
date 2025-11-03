from typing import Any, Dict, List
import json
import requests

from ..state import AgentState
from ..utils.logger import get_logger
from ..utils.json_parser import extract_json_array
from .common import client, driver_client


def bootstrap_node(state: AgentState) -> Dict[str, Any]:
    """Infer base URL and app from instruction, init driver, and set goal.

    This enables instruction-only runs without explicit goal/URL flags.
    """
    instruction = state.get('instruction') or state.get('goal') or ''
    logger = get_logger()
    if logger:
        logger.log(f"Inferring app and base URL from instruction: '{instruction}'", "INFO")

    prompt = f"""Given the user's instruction, infer the most likely web application and base URL to start from.

Instruction: "{instruction}"

Return ONLY a JSON object with:
{{
  "app_name": "Readable app name, e.g., Linear, Notion, GitHub",
  "base_url": "Canonical login/home URL, e.g., https://linear.app, https://www.notion.so/",
  "normalized_goal": "A concise restatement of the user's goal"
}}"""

    # Small retry for bootstrap inference
    attempts = 2
    last_err = None
    for _ in range(attempts):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=[
                    {"role": "system", "content": "Infer target app and base URL for web automation. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ]
            )
            break
        except Exception as e:
            last_err = e
    else:
        raise RuntimeError(f"Bootstrap inference failed: {last_err}")

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

    # Initialize driver at inferred base URL (gRPC) with one retry
    try:
        r = driver_client.init(app_name or 'WebApp', base_url)
        if not r.ok:
            raise RuntimeError(r.error or 'Driver init failed')
        if logger:
            logger.log(f"Driver initialized at {base_url}", "SUCCESS")
    except Exception as e:
        try:
            r = driver_client.init(app_name or 'WebApp', base_url)
            if not r.ok:
                raise RuntimeError(r.error or 'Driver init failed')
            if logger:
                logger.log(f"Driver initialized at {base_url} (after retry)", "SUCCESS")
        except Exception as e2:
            if logger:
                logger.log(f"Driver init error: {e2}", "ERROR")
            return { 'error': str(e2) }

    # Goal decomposition: Parse goal into ordered sub-tasks
    if logger:
        logger.log("Decomposing goal into sub-tasks...", "INFO")
    sub_tasks = _decompose_goal(normalized_goal)
    if sub_tasks:
        if logger:
            logger.log(f"Identified {len(sub_tasks)} sub-task(s)", "INFO")
            for i, task in enumerate(sub_tasks):
                logger.log(f"{i+1}. {task.get('description', 'N/A')} [{task.get('type', 'N/A')}]", "INFO")
    else:
        if logger:
            logger.log("No sub-tasks parsed (treating as single task)", "WARNING")

    return {
        'goal': normalized_goal,
        'app_name': app_name or 'WebApp',
        'base_url': base_url,
        'current_url': base_url,
        'sub_tasks': sub_tasks,
        'current_sub_task_index': 0,
    }


def _decompose_goal(goal: str) -> List[Dict[str, Any]]:
    """Parse goal into ordered sub-tasks with verification criteria.
    
    Only decomposes if goal contains multiple independent operations (AND-separated actions).
    Simple goals like "create message to X" should NOT be decomposed into navigation steps.
    """
    prompt = f"""Analyze this goal and ONLY decompose if it contains multiple INDEPENDENT operations.

Goal: "{goal}"

DECOMPOSITION RULES:
- DO NOT decompose simple goals like "create message", "add task", "filter by X"
- DO decompose if goal has explicit multiple actions separated by "and" (e.g., "create project AND assign to John")
- DO NOT create navigation sub-tasks unless explicitly required (e.g., goal says "go to X page then do Y")
- DO NOT infer navigation steps that aren't in the goal text
- If goal is a single action (even if complex), return ONE sub-task, not multiple steps

Examples:
- "Create a message to X" → ONE sub-task: create message
- "Filter issues and change status" → TWO sub-tasks: filter, status_change
- "Go to settings page and change theme" → TWO sub-tasks: navigation, edit
- "Create message to X about Y" → ONE sub-task: create (don't split into navigate/create/edit)

For each sub-task, identify:
1. Description (what needs to be done)
2. Type (navigation, filter, create, edit, delete, assign, status_change, etc.)
3. Required UI context where this action must occur (list_view, detail_view, modal, form, any)
4. Verification patterns (keywords/phrases that would appear in action labels/URLs when this sub-task is completed)

Return JSON array:
[
  {{
    "id": "task_1",
    "description": "Clear description of what must be done",
    "type": "navigation|filter|create|edit|delete|assign|status_change",
    "required_context": "list_view|detail_view|modal|form|any",
    "verification_patterns": ["keyword1", "keyword2"],
    "order_dependent": true,
    "status": "pending",
    "evidence": []
  }}
]

CRITICAL: If goal describes a single workflow (like "create message"), return ONE task, not multiple navigation/edit steps.
Always initialize status as "pending" and evidence as empty array."""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "Parse web automation goals into structured sub-tasks. Return only valid JSON arrays."},
                {"role": "user", "content": prompt},
            ]
        )
        content = response.choices[0].message.content.strip()
        parsed = extract_json_array(content) or []
        
        # Validate and normalize structure
        normalized: List[Dict[str, Any]] = []
        for i, task in enumerate(parsed):
            if not isinstance(task, dict):
                continue
            normalized.append({
                'id': task.get('id', f'task_{i+1}'),
                'description': task.get('description', ''),
                'type': task.get('type', 'unknown'),
                'required_context': task.get('required_context', 'any'),
                'verification_patterns': task.get('verification_patterns', []),
                'order_dependent': task.get('order_dependent', True),
                'status': 'pending',
                'evidence': []
            })
        return normalized
    except Exception as e:
        from ..utils.logger import get_logger as _get_logger
        _lg = _get_logger()
        if _lg:
            _lg.log(f"Goal decomposition failed: {e}", "ERROR")
        return []


