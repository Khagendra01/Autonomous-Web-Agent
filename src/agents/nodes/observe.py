from typing import Any, Dict

from ..state import AgentState
from .common import driver_client
from ..utils.logger import get_logger


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    logger = get_logger()
    step = state['step_count']
    print(f"\n[OBSERVE] Step {step}")
    
    if logger:
        logger.log_section(f"OBSERVE - Step {step}")
    
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
    capped_interactables = all_interactables[:200]
    
    # Track previous interactable count for surge detection
    current_count = len(all_interactables)
    prev_count = state.get('prev_interactable_count', 0)
    element_surge = current_count > prev_count + 10
    
    if logger:
        logger.log(f"URL: {observe.url}")
        logger.log(f"Interactable elements: {len(all_interactables)} (capped to {len(capped_interactables)})")
        logger.log(f"Element count change: {prev_count} → {current_count} (surge: {element_surge})")
        if observe.errors:
            logger.log_list("Errors detected", list(observe.errors), "ERROR")
        
        # Log sample interactables (first 10)
        if all_interactables:
            logger.log_list("Sample interactable elements (first 10)", 
                          all_interactables[:10])
    
    # Store previous elements for temporal comparison
    prev_elements = state.get('interactable_elements') or []
    
    # Update state
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # a11y tree not included in gRPC response for now
        'interactable_elements': capped_interactables,
        'prev_interactable_elements': prev_elements,  # Store previous for temporal comparison
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
        'prev_interactable_count': current_count,  # Store current count for next step
    }
    
    print(f"  URL: {observe.url}")
    if len(all_interactables) > 200:
        print(f"  Found {len(all_interactables)} interactable elements (capped to 200)")
    else:
        print(f"  Found {len(all_interactables)} interactable elements")
    if observe.errors:
        print(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    return updates


