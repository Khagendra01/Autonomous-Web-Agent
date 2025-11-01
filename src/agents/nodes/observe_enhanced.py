"""Enhanced observe node with better DOM processing."""
from typing import Any, Dict

from ..state import AgentState
from ..utils.dom_enhanced import process_interactable_elements
from .common import driver_client


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state with enhanced DOM processing.
    
    This improved version:
    1. Processes elements into a structured selector map
    2. Adds metadata and indexing for LLM consumption
    3. Creates better summaries for context
    """
    print(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state (gRPC)
    observe = driver_client.observe()
    
    # Capture screenshot
    screenshot_bytes = driver_client.screenshot()
    
    # Convert raw interactables to structured format
    raw_interactables = [
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
            'name': inter.label,  # Use label as name
        }
        for inter in observe.interactables
    ]
    
    # Process into enhanced DOM structure
    selector_map = process_interactable_elements(raw_interactables, max_elements=200)
    interactive_elements = selector_map.to_list_dict()
    
    # Update state with enhanced structure
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # Can be enhanced later with full DOM
        'interactable_elements': interactive_elements,
        'selector_map': selector_map,  # Add selector map for easy access
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    # Log summary
    print(f"  URL: {observe.url}")
    stats = selector_map.filter_interactive()
    print(f"  Found {len(interactive_elements)} interactive elements")
    print(f"    - {len([e for e in stats if e.role == 'button'])} buttons")
    print(f"    - {len([e for e in stats if e.role in {'textbox', 'combobox'}])} inputs")
    print(f"    - {len([e for e in stats if e.role == 'link'])} links")
    
    if observe.errors:
        print(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    return updates

