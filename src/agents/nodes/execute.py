from typing import Any, Dict, List
import requests

from ..state import AgentState, ScoredAction
from .common import DRIVER_URL


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    action = state['next_action']
    
    if not action:
        print(f"\n[EXECUTE] No action to execute")
        return {'error': 'No valid action found'}
    
    print(f"\n[EXECUTE] {action.action_type} on '{action.label}' (score: {action.score:.1f})")
    print(f"  Reasoning: {action.reasoning}")
    
    # Build action payload
    payload = {
        'type': action.action_type,
        'selector': action.selector,
    }
    
    if action.action_type == 'type' and action.text:
        payload['text'] = action.text
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if action.selector and action.action_type in ('click', 'type'):
            crop_resp = requests.post(f"{DRIVER_URL}/screenshot_region", json={
                'selector': action.selector,
                'margin': 24,
            }, timeout=10)
            if crop_resp.status_code == 200 and crop_resp.content:
                # Append focused image to screenshots list
                focused_bytes = crop_resp.content
                screenshots = state.get('screenshots') or []
                screenshots = screenshots + [focused_bytes]
                # Track that this focused screenshot corresponds to the current step index
                focused_after_steps = set(state.get('focused_after_steps') or [])
                focused_after_steps.add(state.get('step_count', 0))
            else:
                screenshots = state.get('screenshots') or []
                focused_after_steps = set(state.get('focused_after_steps') or [])
        else:
            screenshots = state.get('screenshots') or []
            focused_after_steps = set(state.get('focused_after_steps') or [])
    except Exception:
        screenshots = state.get('screenshots') or []
        focused_after_steps = set(state.get('focused_after_steps') or [])
    
    # Execute via driver
    try:
        resp = requests.post(f"{DRIVER_URL}/act", json=payload, timeout=60)
        result = resp.json()
        
        if not result.get('ok'):
            print(f"  ❌ Action failed: {result.get('error')}")
            return {
                'error': result.get('error'),
                'stuck_count': state['stuck_count'] + 1
            }
        
        print(f"  ✓ Action executed successfully")

        # Post-action verification for typing: ensure text became visible; retry once if not
        if action.action_type == 'type' and action.text:
            try:
                # Assert the typed text is present in page text
                verify = requests.post(f"{DRIVER_URL}/act", json={
                    'type': 'assert',
                    'kind': 'text_present',
                    'text': str(action.text),
                }, timeout=6)
                ok = verify.ok and (verify.json().get('ok') is True)
                if not ok:
                    # If focus likely still on title and we intended body, send Enter handoff then retype once
                    try:
                        requests.post(f"{DRIVER_URL}/act", json={ 'type': 'press', 'keys': 'Enter' }, timeout=4)
                    except Exception:
                        pass
                    try:
                        requests.post(f"{DRIVER_URL}/act", json=payload, timeout=10)
                        # One last check
                        requests.post(f"{DRIVER_URL}/act", json={
                            'type': 'assert', 'kind': 'text_present', 'text': str(action.text)
                        }, timeout=5)
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Add to history (include text for type actions so we can verify content later)
        action_record = {
            'type': action.action_type,
            'selector': action.selector,
            'label': action.label,
            'score': action.score,
            'reasoning': action.reasoning,
        }
        if action.action_type == 'type' and action.text:
            action_record['text'] = action.text
        
        # Record this action as tried for the current URL to avoid repeating it
        current_url = state.get('current_url') or ''
        tried_map = dict(state.get('tried_actions_by_url') or [])
        if not isinstance(tried_map, dict):
            tried_map = {}
        tried_here = list(tried_map.get(current_url, []))
        action_key = f"{action.action_type}|{action.selector}"
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


