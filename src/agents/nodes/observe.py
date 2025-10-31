from typing import Any, Dict
import requests

from ..state import AgentState
from .common import DRIVER_URL


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    print(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state
    resp = requests.post(f"{DRIVER_URL}/observe")
    data = resp.json()
    
    # Capture screenshot
    screenshot_resp = requests.get(f"{DRIVER_URL}/screenshot")
    screenshot_bytes = screenshot_resp.content
    
    # Cap interactables to avoid excessive token usage downstream
    all_interactables = data.get('interactables') or []
    capped_interactables = all_interactables[:200]

    # Update state
    updates = {
        'current_url': data['url'],
        'dom_snapshot': data['a11y'],
        'interactable_elements': capped_interactables,
        'errors': data.get('errors') or [],
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    print(f"  URL: {data['url']}")
    if len(all_interactables) > 200:
        print(f"  Found {len(all_interactables)} interactable elements (capped to 200)")
    else:
        print(f"  Found {len(all_interactables)} interactable elements")
    if data.get('errors'):
        print(f"  ⚠️  Errors detected: {data['errors']}")
    
    return updates


