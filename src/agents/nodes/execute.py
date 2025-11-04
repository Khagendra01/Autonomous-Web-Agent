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
    
    # Special handling for autocomplete: clicking on role=option elements directly doesn't work reliably
    # Always use keyboard navigation (Enter) instead of clicking autocomplete options
    use_keyboard_for_autocomplete = False
    
    if action.action_type == 'click' and selector:
        # Check if this is a click on a role=option element (autocomplete option)
        element_role = selector_map.get(action.index, {}).get('role', '').lower() if action.index else ''
        is_option_click = (
            'role=option' in selector.lower() or 
            element_role == 'option' or
            selector.startswith('#lui_')  # Asana autocomplete options use #lui_ IDs
        )
        
        if is_option_click:
            # ALWAYS use keyboard navigation for role=option clicks (they don't work reliably when clicked directly)
            use_keyboard_for_autocomplete = True
            print(f"  🔄 Detected autocomplete option click: using keyboard navigation (type + Enter) instead of clicking option")
    
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
            "has_text": bool(payload.get('text')),
            "using_keyboard_for_autocomplete": use_keyboard_for_autocomplete
        })
        
        # For autocomplete scenarios, use keyboard navigation instead of clicking
        if use_keyboard_for_autocomplete:
            # Type the email in the combobox, then press Enter to select the autocomplete option
            print(f"  📝 Using keyboard navigation for autocomplete selection")
            try:
                import time
                import re
                
                # Extract email from the option label
                option_label = selector_map.get(action.index, {}).get('label', '') or ''
                email_to_type = None
                if option_label and '@' in option_label:
                    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', option_label)
                    if email_match:
                        email_to_type = email_match.group(0)
                
                # Find the combobox field
                combobox_selector = None
                for idx, elem_info in selector_map.items():
                    elem_label = (elem_info.get('label', '') or '').lower()
                    elem_role = (elem_info.get('role', '') or '').lower()
                    elem_sel = elem_info.get('selector', '') or ''
                    
                    is_combobox_field = (
                        elem_role == 'combobox' or
                        (elem_role == 'textbox' and ('type the name' in elem_label or 'type' in elem_label and ('name' in elem_label or 'team' in elem_label or 'people' in elem_label))) or
                        'combobox' in elem_sel.lower()
                    )
                    
                    if is_combobox_field:
                        combobox_selector = elem_sel
                        break
                
                if combobox_selector and email_to_type:
                    # Type the email in the combobox
                    print(f"  📧 Typing '{email_to_type}' in combobox field...")
                    type_result = driver_client.act(
                        type='type',
                        selector=combobox_selector,
                        text=email_to_type
                    )
                    
                    if type_result.ok:
                        # Wait for autocomplete dropdown to appear
                        time.sleep(0.5)
                        
                        # Press Enter to select the highlighted option
                        print(f"  ⏎ Pressing Enter to select autocomplete option...")
                        result = driver_client.act(
                            type='press',
                            keys='Enter'
                        )
                        
                        # Wait after pressing Enter to allow UI to update
                        if result.ok:
                            time.sleep(1.0)
                            print(f"  ✓ Enter pressed, waiting for recipient selection to complete...")
                        else:
                            print(f"  ⚠️  Enter key press failed")
                            result = type_result  # Use type result as fallback
                    else:
                        print(f"  ⚠️  Failed to type in combobox, falling back to click")
                        result = type_result
                else:
                    # If we can't find combobox or email, just press Enter (maybe field already has text)
                    print(f"  ⏎ Pressing Enter to select autocomplete option (field may already have text)...")
                    time.sleep(0.3)
                    result = driver_client.act(
                        type='press',
                        keys='Enter'
                    )
                    if result.ok:
                        time.sleep(1.0)
                
                # Fallback to click if keyboard navigation failed
                if not result.ok:
                    print(f"  ⚠️  Keyboard navigation failed, falling back to click")
                    result = driver_client.act(
                        type=payload['type'],
                        selector=payload.get('selector'),
                        text=payload.get('text'),
                        backend_node_id=backend_node_id if backend_node_id and backend_node_id > 0 else None
                    )
            except Exception as e:
                print(f"  ⚠️  Keyboard navigation failed: {e}, falling back to click")
                # Fallback to regular click
                result = driver_client.act(
                    type=payload['type'],
                    selector=payload.get('selector'),
                    text=payload.get('text'),
                    backend_node_id=backend_node_id if backend_node_id and backend_node_id > 0 else None
                )
        else:
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
        if action.action_type == 'type' and action.text and result.ok:
            import time
            
            # Simple wait after typing to allow autocomplete dropdowns to appear
            # This gives the UI time to show autocomplete options before next observation
            time.sleep(0.5)
            
            # Assert the typed text is present in page text (original verification)
            try:
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
        
        # Post-action verification for click actions: check if recipient/form state changed
        if action.action_type == 'click' and result.ok:
            import time
            import re
            
            # Detect if this is a recipient-related click (email selection, combobox option, etc.)
            is_recipient_click = False
            expected_email = None
            
            # Check 1: Clicking on an email link/option (email pattern in label/selector)
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            action_label = (action.label or '').lower()
            action_selector = (selector or '').lower()
            
            if re.search(email_pattern, action.label or '') or re.search(email_pattern, selector or ''):
                is_recipient_click = True
                email_match = re.search(email_pattern, action.label or selector or '')
                if email_match:
                    expected_email = email_match.group(0)
            
            # Check 2: Clicking on role=option after typing in combobox (autocomplete scenario)
            if not is_recipient_click:
                element_role = selector_map.get(action.index, {}).get('role', '').lower() if action.index else ''
                if element_role == 'option':
                    # Check if previous action was typing in a combobox
                    action_history = state.get('action_history', [])
                    if action_history:
                        last_action = action_history[-1]
                        if last_action.get('type') == 'type':
                            last_label = (last_action.get('label') or '').lower()
                            if 'combobox' in last_label or 'type the name' in last_label or 'recipient' in last_label:
                                is_recipient_click = True
                                # Extract email from typed text if available
                                typed_text = last_action.get('text', '')
                                if typed_text and re.search(email_pattern, typed_text):
                                    email_match = re.search(email_pattern, typed_text)
                                    if email_match:
                                        expected_email = email_match.group(0)
            
            # If this is a recipient click, verify the recipient was added
            if is_recipient_click:
                try:
                    # Check immediately if recipient email appears in visible form
                    # We expect the email to appear as a chip/badge or in the filled field
                    if expected_email:
                        # Check immediately (no wait if change already happened)
                        verify = driver_client.act(type='assert', kind='text_present', text=expected_email)
                        email_visible = bool(verify.ok)
                        
                        if email_visible:
                            # Change detected immediately, continue without waiting
                            print(f"  ✓ Recipient verification: email '{expected_email}' detected in UI")
                        else:
                            # No change detected, wait 2 seconds and check again
                            print(f"  ⏳ No change detected, waiting 2 seconds for UI update...")
                            time.sleep(2.0)
                            verify = driver_client.act(type='assert', kind='text_present', text=expected_email)
                            email_visible = bool(verify.ok)
                            
                            if not email_visible:
                                # Still no change after waiting, report warning
                                logger.warning(f"Recipient selection verification: email '{expected_email}' not detected after click", {
                                    "action_label": action.label,
                                    "selector": selector,
                                    "expected_change": "Recipient should be added to message",
                                    "note": "Action reported success but recipient may not have been added - UI may need more time or different interaction"
                                })
                                print(f"  ⚠️  WARNING: Recipient '{expected_email}' may not have been added. UI state verification failed after 2s wait.")
                            else:
                                print(f"  ✓ Recipient verification: email '{expected_email}' detected after wait")
                    else:
                        # No specific email to check, but we can still verify by waiting briefly
                        print(f"  ⏳ Waiting briefly for recipient selection UI update...")
                        time.sleep(0.5)
                except Exception as e:
                    # Don't fail the action if verification fails, just log
                    logger.debug(f"Recipient verification check failed: {e}")
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


