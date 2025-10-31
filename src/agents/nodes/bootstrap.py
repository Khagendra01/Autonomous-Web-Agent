from typing import Any, Dict
import json
import requests

from ..state import AgentState
from .common import client, driver_client


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

    # Initialize driver at inferred base URL (gRPC)
    try:
        r = driver_client.init(app_name or 'WebApp', base_url)
        if not r.ok:
            raise RuntimeError(r.error or 'Driver init failed')
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


