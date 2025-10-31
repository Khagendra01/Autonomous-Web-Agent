from typing import Any, Dict

from ..state import AgentState
from .common import driver_client
from ..utils.logger import get_logger


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    logger = get_logger()
    logger.info(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state (gRPC)
    observe = driver_client.observe()
    # Capture screenshot
    screenshot_bytes = driver_client.screenshot()
    
    # Cap interactables to avoid excessive token usage downstream
    all_interactables = [
        {
            'role': inter.role,
            'label': inter.label,
            'selector': inter.selector,
            'disabled': inter.disabled,
            'tag': inter.tag,
            'classes': list(inter.classes),
            'id': inter.id,
            'href': inter.href,
            'type': inter.type,
            'placeholder': inter.placeholder,
        }
        for inter in observe.interactables
    ]
    capped_interactables = all_interactables

    # Update state
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # a11y tree not included in gRPC response for now
        'interactable_elements': capped_interactables,
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    logger.info(f"  URL: {observe.url}")
    if len(all_interactables) > 200:
        logger.info(f"  Found {len(all_interactables)} interactable elements (capped to 200)")
    else:
        logger.info(f"  Found {len(all_interactables)} interactable elements")
    if observe.errors:
        logger.warning(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    return updates


