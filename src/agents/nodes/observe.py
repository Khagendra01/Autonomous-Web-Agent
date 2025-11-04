from typing import Any, Dict

from ..state import AgentState
from .common import driver_client
from ...dom.adapter import convert_interactables_to_dom_state


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    print(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state (gRPC)
    observe = driver_client.observe()
    # Capture screenshot
    screenshot_bytes = driver_client.screenshot()
    
    # Convert to list of dicts
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
            'backend_node_id': inter.backend_node_id if hasattr(inter, 'backend_node_id') else 0,  # Include backend_node_id
        }
        for inter in observe.interactables
    ]
    
    # Convert to browser-use format
    dom_state = convert_interactables_to_dom_state(all_interactables, max_elements=200)
    llm_representation = dom_state.llm_representation()
    
    # Build selector_map dict for state (serializable format)
    selector_map_dict = {}
    for index, element in dom_state.selector_map.items():
        selector_map_dict[index] = {
            'selector': element.selector,
            'label': element.label,
            'tag': element.tag,
            'role': element.role,
            'type': element.type,
            'placeholder': element.placeholder,
            'backend_node_id': element.backend_node_id,  # Include backend_node_id
        }

    # Update state
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # a11y tree not included in gRPC response for now
        'interactable_elements': all_interactables[:200],  # Keep for backward compat
        'dom_state_llm_text': llm_representation,  # New: browser-use format
        'selector_map': selector_map_dict,  # New: index -> element mapping
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    print(f"  URL: {observe.url}")
    print(f"  Found {len(all_interactables)} interactable elements")
    print(f"  Generated {len(dom_state.selector_map)} indexed elements for LLM")
    if observe.errors:
        print(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    # Show preview of LLM format
    preview_lines = llm_representation.split('\n')[:5]
    if len(preview_lines) < len(llm_representation.split('\n')):
        print(f"  LLM format preview:")
        for line in preview_lines:
            print(f"    {line}")
        print(f"    ... ({len(llm_representation.split('\n')) - 5} more lines)")
    else:
        print(f"  LLM format:")
        for line in preview_lines:
            print(f"    {line}")
    
    return updates


