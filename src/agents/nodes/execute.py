from typing import Any, Dict, List
import requests

from ..state import AgentState, ScoredAction
from .common import driver_client
from ..utils.logger import get_logger


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    logger = get_logger()
    action = state['next_action']
    
    if not action:
        print(f"\n[EXECUTE] No action to execute")
        if logger:
            logger.log("EXECUTE: No action to execute", "WARNING")
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
    
    # Log execution details
    if logger:
        logger.log_section(f"EXECUTE - Step {state.get('step_count', 0)}")
        logger.log_dict("Action Details", {
            'action_type': action.action_type,
            'label': action.label,
            'selector': action.selector,
            'score': action.score,
            'reasoning': action.reasoning,
            'text': action.text if action.action_type == 'type' else None
        })
        logger.log_dict("Payload", payload)
        logger.log(f"Current URL: {state.get('current_url', 'N/A')}")
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if action.selector and action.action_type in ('click', 'type'):
            try:
                focused_bytes = driver_client.screenshot_region(action.selector, margin=24)
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
    
    # Execute via driver
    try:
        if logger:
            logger.log(f"Calling driver_client.act() with payload: {payload}", "DEBUG")
        
        result = driver_client.act(
            type=payload['type'],
            selector=payload.get('selector'),
            text=payload.get('text')
        )
        
        if logger:
            logger.log_dict("Driver Response", {
                'ok': result.ok,
                'error': result.error if hasattr(result, 'error') else None
            })
        
        if not result.ok:
            error_msg = result.error if hasattr(result, 'error') else 'Unknown error'
            print(f"  ❌ Action failed: {error_msg}")
            if logger:
                logger.log(f"Action FAILED: {error_msg}", "ERROR")
                logger.log(f"Failed selector: {payload.get('selector')}", "ERROR")
            return {
                'error': error_msg,
                'stuck_count': state['stuck_count'] + 1
            }
        
        print(f"  ✓ Action executed successfully")
        if logger:
            logger.log("Action executed successfully", "SUCCESS")

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
        import traceback
        if logger:
            logger.log(f"Exception during action execution: {str(e)}", "ERROR")
            logger.log(f"Exception traceback:\n{traceback.format_exc()}", "ERROR")
            logger.log(f"Failed selector: {payload.get('selector')}", "ERROR")
        return {
            'error': str(e),
            'stuck_count': state['stuck_count'] + 1
        }


