from typing import Any, Dict
import hashlib
import json

from ..state import AgentState
from .common import driver_client
from ..utils.logger import get_logger


def _element_key(e: Dict[str, Any]) -> str:
    role = e.get('role', '')
    label = e.get('label', '')
    selector = e.get('selector', '')
    return f"{role}|{label}|{selector}"


def _parse_meta_tokens(classes: list[str]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        'bbox': None,
        'inViewport': None,
        'center': None,
        'pointerEvents': None,
        'opacity': None,
        'zIndex': None,
        'aria': {},
        'focus': {},
        'elementKey': None,
    }
    if not classes:
        return meta
    for c in classes:
        if not isinstance(c, str):
            continue
        if c.startswith('__bbox_'):
            try:
                _, xs, ys, ws, hs = c.split('_', 4)
                meta['bbox'] = {
                    'x': int(xs), 'y': int(ys), 'width': int(ws), 'height': int(hs)
                }
            except Exception:
                pass
        elif c.startswith('__vp_'):
            try:
                meta['inViewport'] = (c.split('_', 1)[1] == '1')
            except Exception:
                pass
        elif c.startswith('__cx_'):
            try:
                cx = int(c.split('_', 1)[1])
                center = meta.get('center') or {}
                center['x'] = cx
                meta['center'] = center
            except Exception:
                pass
        elif c.startswith('__cy_'):
            try:
                cy = int(c.split('_', 1)[1])
                center = meta.get('center') or {}
                center['y'] = cy
                meta['center'] = center
            except Exception:
                pass
        elif c.startswith('__pe_'):
            meta['pointerEvents'] = c.split('_', 2)[2] if '_' in c else None
        elif c.startswith('__op_'):
            try:
                meta['opacity'] = float(c.split('_', 1)[1])
            except Exception:
                pass
        elif c.startswith('__zi_'):
            meta['zIndex'] = c.split('_', 1)[1]
        elif c.startswith('__aria_'):
            try:
                # __aria_key_value
                _, rest = c.split('__aria_', 1)
                k, v = rest.split('_', 1)
                meta.setdefault('aria', {})[k] = v
            except Exception:
                pass
        elif c.startswith('__tb_'):
            try:
                meta.setdefault('focus', {})['tabindex'] = int(c.split('_', 1)[1])
            except Exception:
                pass
        elif c.startswith('__fc_'):
            try:
                meta.setdefault('focus', {})['focusable'] = (c.split('_', 1)[1] == '1')
            except Exception:
                pass
        elif c == '__ce_1':
            meta.setdefault('focus', {})['contentEditable'] = True
        elif c.startswith('__ek_'):
            meta['elementKey'] = c.split('_', 1)[1]
    return meta


def _enrich_with_meta(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    enriched: list[Dict[str, Any]] = []
    for e in items:
        classes = e.get('classes') or []
        meta = _parse_meta_tokens(classes)
        if meta.get('bbox') is not None:
            e['bbox'] = meta['bbox']
        if meta.get('inViewport') is not None:
            e['inViewport'] = meta['inViewport']
        if meta.get('center') is not None:
            e['center'] = meta['center']
        if meta.get('pointerEvents') is not None:
            e['pointerEvents'] = meta['pointerEvents']
        if meta.get('opacity') is not None:
            e['opacity'] = meta['opacity']
        if meta.get('zIndex') is not None:
            e['zIndex'] = meta['zIndex']
        if meta.get('aria'):
            e['aria'] = meta['aria']
        if meta.get('focus'):
            e['focus'] = meta['focus']
        if meta.get('elementKey') is not None:
            e['elementKey'] = meta['elementKey']
        enriched.append(e)
    return enriched


def _delta_prune(
    all_interactables: list[Dict[str, Any]],
    prev_elements: list[Dict[str, Any]],
    hard_cap: int,
    unchanged_sample_cap: int,
):
    prev_keys = set()
    try:
        prev_keys = {_element_key(e) for e in prev_elements}
    except Exception:
        prev_keys = set()

    current_pairs = [(_element_key(e), e) for e in all_interactables]
    changed = [e for (k, e) in current_pairs if k not in prev_keys]
    unchanged = [e for (k, e) in current_pairs if k in prev_keys]

    pruned = changed[:hard_cap]
    unchanged_added = 0
    if len(pruned) < hard_cap and unchanged:
        remaining = hard_cap - len(pruned)
        take = min(unchanged_sample_cap, remaining)
        pruned += unchanged[:take]
        unchanged_added = take

    # Preserve some inputs if space remains
    if len(pruned) < hard_cap:
        input_candidates = [e for e in all_interactables if (e.get('role') or '').lower() in ('textbox', 'searchbox')]
        if input_candidates:
            need = min(3, hard_cap - len(pruned))
            # append first few inputs not already included
            existing_ids = {id(x) for x in pruned}
            added = 0
            for e in input_candidates:
                if id(e) in existing_ids:
                    continue
                pruned.append(e)
                added += 1
                if added >= need:
                    break

    if not pruned:
        pruned = all_interactables[:hard_cap]

    return pruned, len(changed), unchanged_added


def _compute_interactable_fingerprint(all_interactables: list[Dict[str, Any]]) -> str:
    try:
        fp_basis = [
            {
                'role': e.get('role', ''),
                'label': e.get('label', ''),
                'selector': e.get('selector', ''),
                'disabled': bool(e.get('disabled', False)),
            }
            for e in all_interactables
        ]
        fp_json = json.dumps(fp_basis, separators=(",", ":"), ensure_ascii=False)
        return hashlib.md5(fp_json.encode('utf-8')).hexdigest()
    except Exception:
        return ""


def _log_observation(
    logger,
    url: str,
    all_count: int,
    pruned_count: int,
    changed_count: int,
    unchanged_added: int,
    prev_count: int,
    current_count: int,
    errors: list,
    sample: list[Dict[str, Any]],
):
    if not logger:
        return
    logger.log(f"URL: {url}")
    logger.log(
        f"Interactable elements: {all_count} (pruned to {pruned_count}; changed={changed_count}, unchanged_sample={max(0, unchanged_added)})"
    )
    element_surge = current_count > prev_count + 10
    logger.log(f"Element count change: {prev_count} → {current_count} (surge: {element_surge})")
    if errors:
        logger.log_list("Errors detected", list(errors), "ERROR")
    if sample:
        logger.log_list("Sample interactable elements (first 10)", sample[:10])


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
    # Enrich with meta extracted from classes tokens (if present)
    all_interactables = _enrich_with_meta(all_interactables)

    # Delta-based capping: prefer changed elements + small sample of unchanged
    prev_elements = state.get('interactable_elements') or []
    # Configurable caps
    hard_cap = int(state.get('observe_cap') or 120)  # default lower than previous 200
    unchanged_sample_cap = max(10, min(40, hard_cap // 3))  # keep a small stable sample

    pruned, changed_count, unchanged_added = _delta_prune(
        all_interactables, prev_elements, hard_cap, unchanged_sample_cap
    )
    
    # Track previous interactable count for surge detection
    current_count = len(all_interactables)
    prev_count = state.get('prev_interactable_count', 0)
    element_surge = current_count > prev_count + 10
    
    if logger:
        _log_observation(
            logger,
            observe.url,
            len(all_interactables),
            len(pruned),
            changed_count,
            unchanged_added,
            prev_count,
            current_count,
            list(observe.errors),
            all_interactables,
        )
    
    # Compute a stable fingerprint of the interactables for caching downstream
    interactable_fingerprint = _compute_interactable_fingerprint(all_interactables)

    # Update state
    updates = {
        'current_url': observe.url,
        'dom_snapshot': None,  # a11y tree not included in gRPC response for now
        'interactable_elements': pruned,
        'interactable_elements_all': all_interactables,  # full set for non-LLM consumers
        'prev_interactable_elements': prev_elements,  # Store previous for temporal comparison
        'errors': list(observe.errors),
        'screenshot_bytes': screenshot_bytes,
        'screenshots': (state.get('screenshots') or []) + [screenshot_bytes],
        'prev_interactable_count': current_count,  # Store current count for next step
        'interactable_fingerprint': interactable_fingerprint,
    }
    
    print(f"  URL: {observe.url}")
    print(f"  Found {len(all_interactables)} interactable elements (pruned to {len(pruned)})")
    if observe.errors:
        print(f"  ⚠️  Errors detected: {list(observe.errors)}")
    
    return updates


