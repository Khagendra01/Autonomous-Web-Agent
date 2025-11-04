from typing import Any, Dict, List
import requests

from ..state import AgentState, ScoredAction
from .common import driver_client
from ..utils.logger import get_logger


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    action = state['next_action']
    
    if not action:
        print(f"\n[EXECUTE] No action to execute")
        return {'error': 'No valid action found'}
    
    print(f"\n[EXECUTE] {action.action_type} on '{action.label}' (score: {action.score:.1f})")
    print(f"  Reasoning: {action.reasoning}")
    
    logger = get_logger()
    logger.section(f"EXECUTE Step {state.get('step_count', 0)}")
    
    # Resolve selector and backend_node_id from index if using browser-use format
    selector = action.selector
    backend_node_id = None
    if action.index is not None:
        selector_map = state.get('selector_map', {})
        if action.index in selector_map:
            element_info = selector_map[action.index]
            selector = element_info['selector']
            # Get stored backend_node_id (may be 0 if unavailable)
            # Note: The driver will always do lazy resolution at execution time to get fresh backend_node_id
            stored_backend_id = element_info.get('backend_node_id', 0)
            # Only use stored backend_node_id if it looks like a real CDP ID (>= 1000)
            # Small values are likely indices, not real CDP IDs
            backend_node_id = stored_backend_id if stored_backend_id >= 1000 else None
            
            if backend_node_id:
                print(f"  Resolved index {action.index} -> selector: {selector}, stored_backend_node_id: {backend_node_id} (will resolve fresh at execution)")
            else:
                print(f"  Resolved index {action.index} -> selector: {selector} (backend_node_id will be resolved at execution time)")
            
            logger.cdp(f"Resolved element for execution", {
                "index": action.index,
                "stored_backend_node_id": stored_backend_id,
                "backend_node_id": backend_node_id,  # Only valid if >= 1000
                "selector": selector,
                "label": element_info.get('label'),
                "action_type": action.action_type
            })
        else:
            print(f"  ⚠️  Warning: index {action.index} not found in selector_map, using fallback")
            logger.warning(f"Index not found in selector_map", {"index": action.index})
    
    # Build action payload
    payload = {
        'type': action.action_type,
        'selector': selector,
    }
    
    if action.action_type == 'type' and action.text:
        payload['text'] = action.text
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if selector and action.action_type in ('click', 'type'):
            try:
                focused_bytes = driver_client.screenshot_region(selector, margin=24)
                screenshots = state.get('screenshots') or []
                screenshots = screenshots + [focused_bytes]
                # Track that this focused screenshot corresponds to the current step index
                focused_after_steps = set(state.get('focused_after_steps') or [])
                focused_after_steps.add(state.get('step_count', 0))
            except Exception:
                screenshots = state.get('screenshots') or []
                focused_after_steps = set(state.get('focused_after_steps') or [])
        else:
            screenshots = state.get('screenshots') or []
            focused_after_steps = set(state.get('focused_after_steps') or [])
    except Exception:
        screenshots = state.get('screenshots') or []
        focused_after_steps = set(state.get('focused_after_steps') or [])
    
    # Execute via driver with retry and SmartLocate fallback
    try:
        logger.info(f"Executing action", {
            "action_type": payload['type'],
            "selector": payload.get('selector'),
            "backend_node_id": backend_node_id if backend_node_id and backend_node_id > 0 else None,
            "has_text": bool(payload.get('text'))
        })
        
        result = driver_client.act(
            type=payload['type'],
            selector=payload.get('selector'),
            text=payload.get('text'),
            backend_node_id=backend_node_id if backend_node_id and backend_node_id > 0 else None
        )
        
        logger.info(f"Action execution result", {
            "success": result.ok,
            "error": result.error if not result.ok else None
        })
        
        if not result.ok:
            # Try SmartLocate as fallback if we have a label
            if action.label and action.action_type == 'click':
                print(f"  ⚠️  Primary selector failed, trying SmartLocate fallback...")
                try:
                    # Use short label for SmartLocate
                    from ...drivers.utils.selector_generator import extract_short_label
                    short_label = extract_short_label(action.label, max_words=3)
                    smart_result = driver_client.smart_locate(
                        description=short_label,
                        failed_selector=selector,
                        use_llm=True
                    )
                    if smart_result.ok and smart_result.selector:
                        print(f"  ✓ SmartLocate found alternative: {smart_result.selector} (strategy: {smart_result.strategy})")
                        # Retry with smart selector (no backend_node_id for SmartLocate results)
                        result = driver_client.act(
                            type=payload['type'],
                            selector=smart_result.selector,
                            text=payload.get('text'),
                            backend_node_id=None
                        )
                        if result.ok:
                            print(f"  ✓ Action executed successfully via SmartLocate")
                        else:
                            print(f"  ❌ SmartLocate selector also failed: {result.error}")
                    else:
                        print(f"  ❌ SmartLocate failed: {smart_result.error}")
                except Exception as smart_e:
                    print(f"  ❌ SmartLocate exception: {smart_e}")
            
            if not result.ok:
                print(f"  ❌ Action failed: {result.error}")
                return {
                    'error': result.error,
                    'stuck_count': state['stuck_count'] + 1
                }
        else:
            print(f"  ✓ Action executed successfully")

        # Post-action verification for typing: ensure text became visible; retry once if not
        if action.action_type == 'type' and action.text:
            try:
                # Assert the typed text is present in page text
                verify = driver_client.act(type='assert', kind='text_present', text=str(action.text))
                ok = bool(verify.ok)
                if not ok:
                    # If focus likely still on title and we intended body, send Enter handoff then retype once
                    try:
                        driver_client.act(type='press', keys='Enter')
                    except Exception:
                        pass
                    try:
                        driver_client.act(type=payload['type'], selector=payload.get('selector'), text=payload.get('text'))
                        # One last check
                        driver_client.act(type='assert', kind='text_present', text=str(action.text))
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Add to history (include text for type actions so we can verify content later)
        # IMPORTANT: Use RESOLVED selector (not action.selector) so filtering works correctly
        action_record = {
            'type': action.action_type,
            'selector': selector,  # Use resolved selector, not action.selector
            'label': action.label,
            'score': action.score,
            'reasoning': action.reasoning,
        }
        if action.action_type == 'type' and action.text:
            action_record['text'] = action.text
        
        # Record this action as tried for the current URL to avoid repeating it
        current_url = state.get('current_url') or ''
        tried_map = dict(state.get('tried_actions_by_url') or {})
        if not isinstance(tried_map, dict):
            tried_map = {}
        tried_here = list(tried_map.get(current_url, []))
        # Use resolved selector for action key
        action_key = f"{action.action_type}|{selector}"
        if action_key not in tried_here:
            tried_here.append(action_key)
        tried_map[current_url] = tried_here
        
        return {
            'action_history': state['action_history'] + [action_record],
            'step_count': state['step_count'] + 1,
            'stuck_count': 0,
            'tried_actions_by_url': tried_map,
            'screenshots': screenshots,
            'focused_after_steps': list(focused_after_steps),
        }
        
    except Exception as e:
        print(f"  ❌ Exception during action: {e}")
        return {
            'error': str(e),
            'stuck_count': state['stuck_count'] + 1
        }


