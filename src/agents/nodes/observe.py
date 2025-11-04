from typing import Any, Dict

from ..state import AgentState
from .common import driver_client
from ...dom.adapter import convert_interactables_to_dom_state
from ..utils.logger import get_logger


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    logger = get_logger()
    step = state['step_count']
    logger.section(f"OBSERVE Step {step}")
    
    print(f"\n[OBSERVE] Step {step}")
    
    # Get current page state (gRPC)
    try:
        observe = driver_client.observe()
    except Exception as e:
        error_msg = str(e)
        if "not initialized" in error_msg.lower() or "init" in error_msg.lower():
            raise RuntimeError(f"Browser not initialized. Bootstrap may have failed. Original error: {error_msg}")
        raise
    # Capture screenshot
    screenshot_bytes = driver_client.screenshot()
    
    logger.info(f"Observed page state", {
        "url": observe.url,
        "interactables_count": len(observe.interactables),
        "errors": list(observe.errors)
    })
    
    # Convert to list of dicts
    all_interactables = []
    for inter in observe.interactables:
        backend_node_id = inter.backend_node_id if hasattr(inter, 'backend_node_id') else 0
        inter_dict = {
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
            'backend_node_id': backend_node_id,
        }
        all_interactables.append(inter_dict)
        
        # Log label extraction details
        logger.label(f"Extracted interactable", {
            "backend_node_id": backend_node_id,
            "role": inter.role,
            "label": inter.label,
            "label_length": len(inter.label),
            "selector": inter.selector,
            "tag": inter.tag,
            "id": inter.id
        })
    
    # Convert to browser-use format
    dom_state = convert_interactables_to_dom_state(all_interactables, max_elements=200)
    llm_representation = dom_state.llm_representation()
    
    logger.llm(f"Generated LLM representation", {
        "total_length": len(llm_representation),
        "preview": llm_representation[:500] + "..." if len(llm_representation) > 500 else llm_representation
    })
    
    # Build selector_map dict for state (serializable format)
    # Key is llm_index (enumeration index), value contains element info
    selector_map_dict = {}
    for index, element in dom_state.selector_map.items():
        selector_map_dict[index] = {
            'selector': element.selector,
            'label': element.label,
            'tag': element.tag,
            'role': element.role,
            'type': element.type,
            'placeholder': element.placeholder,
            'backend_node_id': element.backend_node_id,  # Real CDP backend_node_id (0 if unavailable, will be resolved at execution)
            'llm_index': element.llm_index,  # LLM reference index
        }
    
    logger.info(f"Built selector map", {
        "total_elements": len(selector_map_dict),
        "sample_elements": {k: v for k, v in list(selector_map_dict.items())[:5]}
    })

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
    total_lines = len(llm_representation.split('\n'))
    if len(preview_lines) < total_lines:
        print(f"  LLM format preview:")
        for line in preview_lines:
            print(f"    {line}")
        remaining = total_lines - 5
        print(f"    ... ({remaining} more lines)")
    else:
        print(f"  LLM format:")
        for line in preview_lines:
            print(f"    {line}")
    
    return updates


