from typing import Any, Dict
import hashlib
import json

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
    
    # Collect interactables
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

    # Delta-based capping: prefer changed elements + small sample of unchanged
    prev_elements = state.get('interactable_elements') or []
    prev_keys = set()
    try:
        prev_keys = {f"{e.get('role','')}|{e.get('label','')}|{e.get('selector','')}" for e in prev_elements}
    except Exception:
        prev_keys = set()

    current_pairs = []
    for e in all_interactables:
        key = f"{e.get('role','')}|{e.get('label','')}|{e.get('selector','')}"
        current_pairs.append((key, e))

    changed = [e for (k, e) in current_pairs if k not in prev_keys]
    unchanged = [e for (k, e) in current_pairs if k in prev_keys]

    # Configurable caps
    hard_cap = int(state.get('observe_cap') or 120)  # default lower than previous 200
    unchanged_sample_cap = max(10, min(40, hard_cap // 3))  # keep a small stable sample

    # Build pruned set: all changed (up to cap) + small sample of unchanged to preserve context
    pruned = changed[:hard_cap]
    if len(pruned) < hard_cap and unchanged:
        # simple head sample; could be improved with salience/role-based sampling
        remaining = hard_cap - len(pruned)
        pruned += unchanged[:min(unchanged_sample_cap, remaining)]

    # Fallback if nothing changed: take head sample
    if not pruned:
        pruned = all_interactables[:hard_cap]
    
    # Track previous interactable count for surge detection
    current_count = len(all_interactables)
    prev_count = state.get('prev_interactable_count', 0)
    element_surge = current_count > prev_count + 10
    
    if logger:
        logger.log(f"URL: {observe.url}")
        logger.log(f"Interactable elements: {len(all_interactables)} (pruned to {len(pruned)}; changed={len(changed)}, unchanged_sample={max(0, len(pruned)-len(changed))})")
        logger.log(f"Element count change: {prev_count} → {current_count} (surge: {element_surge})")
        if observe.errors:
            logger.log_list("Errors detected", list(observe.errors), "ERROR")
        
        # Log sample interactables (first 10)
        if all_interactables:
            logger.log_list("Sample interactable elements (first 10)", 
                          all_interactables[:10])
    
    # Compute a stable fingerprint of the interactables for caching downstream
    try:
        # Only include stable, small fields
        fp_basis = [
            {
                'role': e.get('role',''),
                'label': e.get('label',''),
                'selector': e.get('selector',''),
                'disabled': bool(e.get('disabled', False)),
            }
            for e in all_interactables
        ]
        fp_json = json.dumps(fp_basis, separators=(",", ":"), ensure_ascii=False)
        interactable_fingerprint = hashlib.md5(fp_json.encode('utf-8')).hexdigest()
    except Exception:
        interactable_fingerprint = ""

    # Update state
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # a11y tree not included in gRPC response for now
        'interactable_elements': pruned,
        'interactable_elements_all': all_interactables,  # full set for non-LLM consumers
        'prev_interactable_elements': prev_elements,  # Store previous for temporal comparison
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
        'prev_interactable_count': current_count,  # Store current count for next step
        'interactable_fingerprint': interactable_fingerprint,
    }
    
    print(f"  URL: {observe.url}")
    print(f"  Found {len(all_interactables)} interactable elements (pruned to {len(pruned)})")
    if observe.errors:
        print(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    return updates


