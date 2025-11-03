from typing import Any, Dict, List

from ..state import AgentState, ScoredAction
from .common import driver_client
from ..utils.logger import get_logger
from ..utils.action_registry import validate_action_params
from urllib.parse import urlparse


def _resolve_action_selector(action: ScoredAction, state: AgentState) -> str:
    """Resolve action selector from index if needed (best practice: index-based actions)."""
    # If selector looks like an index (numeric), try to resolve from llm_index_to_selector
    selector = action.selector
    try:
        # Check if selector is just a number (index)
        if selector.isdigit():
            index = int(selector)
            index_map = state.get('llm_index_to_selector') or {}
            if index in index_map:
                resolved = index_map[index]
                if logger := get_logger():
                    logger.log(f"Resolved action index {index} to selector: {resolved}", "DEBUG")
                return resolved
            else:
                if logger := get_logger():
                    logger.log(f"Warning: Index {index} not found in llm_index_to_selector", "WARNING")
    except (ValueError, AttributeError):
        pass
    
    # Return original selector if not an index or resolution failed
    return selector


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    logger = get_logger()
    action = state['next_action']
    
    if not action:
        if logger:
            logger.log("EXECUTE: No action to execute", "WARNING")
        return {'error': 'No valid action found'}
    
    # Prevent duplicate execution within the same step
    current_step = int(state.get('step_count', 0))
    if state.get('execution_step_lock') == current_step:
        if logger:
            logger.log(f"EXECUTE: Skipped duplicate execute in step {current_step}", "WARNING")
        return {
            'step_count': state['step_count'],
        }

    if logger:
        logger.log(f"EXECUTE: {action.action_type} on '{action.label}' (score: {action.score:.1f})", "INFO")
        logger.log(f"Reasoning: {action.reasoning}", "INFO")
    
    # Resolve selector from index if needed (best practice: index-based actions)
    resolved_selector = _resolve_action_selector(action, state)
    
    # Derive text for type actions if missing (best practice: graceful fallback)
    text_value = action.text
    if action.action_type == 'type' and not text_value:
        try:
            # Prefer goal over instruction for better structured text (goal is decomposed and may have quotes)
            from .scoring import _summarize_instruction
            goal_or_instr = (state.get('goal') or state.get('instruction') or '').strip()
            if goal_or_instr:
                # Use the same extraction logic as scoring node
                text_value = _summarize_instruction(goal_or_instr, max_len=120)
        except Exception:
            text_value = None
    
    # Best practice: Validate action parameters before execution
    try:
        params = {
            'selector': resolved_selector,
        }
        if text_value:
            params['text'] = text_value
        
        # Validate parameters
        validated_params = validate_action_params(action.action_type, params)
    except ValueError as e:
        if logger:
            logger.log(f"Action parameter validation failed: {e}", "ERROR")
        return {
            'error': f"Invalid action parameters: {e}",
            'stuck_count': state.get('stuck_count', 0) + 1,
            'short_term_error_memory': f"Action validation failed: {e}. Please check action parameters.",
        }
    
    # Build action payload from validated params
    # Note: validation already ensures required params are present
    payload = {
        'type': action.action_type,
        **validated_params
    }
    
    # Log execution details
    if logger:
        logger.log_section(f"EXECUTE - Step {state.get('step_count', 0)}")
        logger.log_dict("Action Details", {
            'action_type': action.action_type,
            'label': action.label,
            'selector': action.selector,
            'score': action.score,
            'reasoning': action.reasoning,
            'text': text_value if action.action_type == 'type' else None
        })
        logger.log_dict("Payload", payload)
        logger.log(f"Current URL: {state.get('current_url', 'N/A')}")
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if resolved_selector and action.action_type in ('click', 'type'):
            try:
                focused_bytes = driver_client.screenshot_region(resolved_selector, margin=24)
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
    
    # Optional micro-batch: if an intended option is provided, perform a 2-step sequence
    try:
        intended_option = (state.get('intended_option') or '').strip()
    except Exception:
        intended_option = ''

    # Execute via driver
    try:
        if logger:
            logger.log(f"Calling driver_client.act() with payload: {payload}", "DEBUG")
        
        # If we have an intended option and current action is a click, try sequence: open control → select option
        if intended_option and action.action_type == 'click' and action.selector and 'role=button' in (action.selector or ''):
            seq = [action.selector, f'role=option[name="{intended_option}"]']
            if logger:
                logger.log(f"Executing batched sequence: {seq}", "DEBUG")
            result = driver_client.act(type='sequence', selectors=seq)
        else:
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
            if logger:
                logger.log(f"Action FAILED: {error_msg}", "ERROR")
                logger.log(f"Failed selector: {payload.get('selector')}", "ERROR")
            
            # Best practice: Structured error feedback (short-term memory for LLM)
            short_term_memory = f"Action '{action.action_type}' failed on selector '{resolved_selector}'. Error: {error_msg}"
            
            # Check available actions for short-term context
            available_actions = state.get('scored_actions') or []
            if available_actions:
                top_alternatives = [a for a in available_actions[:3] if a != action]
                if top_alternatives:
                    short_term_memory += f". Available alternatives: {', '.join([f'{a.action_type} on {a.label}' for a in top_alternatives])}"
            
            return {
                'error': error_msg,
                'stuck_count': state['stuck_count'] + 1,
                'short_term_error_memory': short_term_memory,
            }
        
        if logger:
            logger.log("Action executed successfully", "SUCCESS")
        
        # Best practice: Clear short-term error memory on success (it was shown once)
        # Long-term error memory persists for context
        return_updates = {
            'short_term_error_memory': None,  # Clear after successful action
        }

        # Update selector memory registry on success
        try:
            registry = dict(state.get('selector_registry') or {})
            label_key = (action.label or '').strip().lower()
            if label_key:
                entry = registry.get(label_key) or {}
                sel = payload.get('selector') or ''
                if sel:
                    # Track success counts per selector
                    count = int(entry.get(sel) or 0)
                    entry[sel] = count + 1
                    registry[label_key] = entry
                    state['selector_registry'] = registry
        except Exception:
            pass

        # Brief readiness await after context-opening clicks (generic, dynamic)
        try:
            if action.action_type == 'click':
                lbl = (action.label or '').lower()
                if any(t in lbl for t in ['create', 'new', 'compose', 'open', 'edit']):
                    try:
                        driver_client.act(type='await', kind='timeout', timeout=300)
                    except Exception:
                        pass
        except Exception:
            pass

        # Post-action verification for typing: ensure text became visible; retry once if not
        if action.action_type == 'type' and text_value:
            try:
                # Assert the typed text is present in page text (use text_value, not action.text)
                verify = driver_client.act(type='assert', kind='text_present', text=str(text_value))
                ok = bool(verify.ok)
                
                # Additional validation: check if text was extracted correctly from goal
                # If we typed the full instruction instead of just the title, log a warning
                goal_text = (state.get('goal') or state.get('instruction') or '').strip()
                if goal_text and len(text_value) > 50:
                    # Check if text_value looks like the full instruction (not just a title)
                    if goal_text.lower()[:50] in text_value.lower() or text_value.lower() in goal_text.lower()[:len(text_value)+20]:
                        if logger:
                            logger.log(f"WARNING: Typed text appears to be full instruction ({len(text_value)} chars) instead of extracted title. Text: '{text_value[:60]}...'", "WARNING")
                            logger.log(f"Goal was: '{goal_text[:80]}...'", "WARNING")
                
                if not ok:
                    if logger:
                        logger.log(f"Text verification failed: '{text_value[:50]}...' not found in page", "WARNING")
                    # If focus likely still on title and we intended body, send Enter handoff then retype once
                    try:
                        driver_client.act(type='press', keys='Enter')
                    except Exception:
                        pass
                    try:
                        driver_client.act(type=payload['type'], selector=payload.get('selector'), text=payload.get('text'))
                        # One last check (use text_value)
                        verify2 = driver_client.act(type='assert', kind='text_present', text=str(text_value))
                        if not bool(verify2.ok) and logger:
                            logger.log(f"Text verification failed after retry: '{text_value[:50]}...'", "WARNING")
                    except Exception:
                        pass
                elif logger:
                    # Log successful verification for debugging
                    logger.log(f"Text verification passed: '{text_value[:50]}...' found in page", "DEBUG")
            except Exception as e:
                if logger:
                    logger.log(f"Text verification exception: {e}", "DEBUG")
                pass
        
        # Deterministic post-action verification for status changes
        predicate_truths = dict(state.get('predicate_truths') or {})
        try:
            label_lower = (action.label or '').lower()
            # If action likely changed status (e.g., clicking 'Done' or status button), poll for 'Done'
            if any(term in label_lower for term in ['done', 'status', 'in progress']):
                attempts = 3
                observed_done = False
                for _ in range(attempts):
                    try:
                        verify = driver_client.act(type='assert', kind='text_present', text='Done')
                        if bool(verify.ok):
                            observed_done = True
                            break
                    except Exception:
                        pass
                    try:
                        # small backoff to allow UI to update
                        driver_client.act(type='await', kind='timeout', timeout=250)
                    except Exception:
                        pass
                if observed_done:
                    predicate_truths['statusIsDone'] = True
        except Exception:
            predicate_truths = dict(state.get('predicate_truths') or {})

        # Add to history (include text for type actions so we can verify content later)
        # Store the URL where this action occurred for proper context verification
        # Best practice: Store resolved selector for consistent tracking
        current_url = state.get('current_url') or ''
        action_record = {
            'type': action.action_type,
            'selector': resolved_selector,  # Store resolved selector, not original index
            'label': action.label,
            'score': action.score,
            'reasoning': action.reasoning,
            'url': current_url,  # Store URL where action occurred for context verification
        }
        if action.action_type == 'type':
            # Persist the actual text used (derived or provided)
            if text_value:
                action_record['text'] = text_value
        
        # Anchor target entity when evidence appears (URL or label contains an ID)
        target_entity = state.get('target_entity') or {}
        try:
            # If URL indicates an entity detail, capture it
            if '/issue/' in current_url and 'id' not in target_entity:
                # crude parse: /issue/<ID>/...
                try:
                    parts = current_url.split('/issue/')[1].split('/')
                    issue_id = parts[0]
                except Exception:
                    issue_id = None
                if issue_id:
                    target_entity = {
                        'id': issue_id,
                        'url': current_url,
                    }
            # If label shows an ID token like ABC-123, capture it
            if not target_entity and action.label:
                import re
                m = re.search(r"\b([A-Z]{2,}-\d+)\b", action.label)
                if m:
                    target_entity = {
                        'id': m.group(1),
                        'url': current_url or None,
                    }
        except Exception:
            target_entity = state.get('target_entity') or {}

        # Record this action as tried for the current URL to avoid repeating it
        # Use resolved_selector to ensure consistent tracking (best practice)
        tried_map = dict(state.get('tried_actions_by_url') or {})
        if not isinstance(tried_map, dict):
            tried_map = {}
        tried_here = list(tried_map.get(current_url, []))
        # Use resolved selector for tracking to prevent loops with index-based actions
        # Record both a base key and (for type) a text-specific key
        base_key = f"{action.action_type}|{resolved_selector}"
        if base_key not in tried_here:
            tried_here.append(base_key)
        if action.action_type == 'type' and text_value:
            text_key = f"{action.action_type}|{resolved_selector}|{text_value[:50]}"
            if text_key not in tried_here:
                tried_here.append(text_key)
        tried_map[current_url] = tried_here
        
        # Track in-form progress: after any type action, increment; after selecting an option, too
        form_progress = int(state.get('form_progress') or 0)
        try:
            if action.action_type == 'type':
                form_progress += 1
            elif action.action_type == 'click' and isinstance(action.selector, str) and 'role=option' in action.selector.lower():
                form_progress += 1
        except Exception:
            pass

        return {
            'action_history': state['action_history'] + [action_record],
            'step_count': state['step_count'] + 1,
            'stuck_count': 0,
            'tried_actions_by_url': tried_map,
            'screenshots': screenshots,
            'focused_after_steps': list(focused_after_steps),
            'execution_step_lock': current_step,
            'target_entity': target_entity or state.get('target_entity'),
            'predicate_truths': predicate_truths,
            'selector_registry': state.get('selector_registry') or registry if 'registry' in locals() else state.get('selector_registry'),
            'form_progress': form_progress,
            **return_updates,  # Include error memory clearing
        }
        
    except Exception as e:
        import traceback
        if logger:
            logger.log(f"Exception during action execution: {str(e)}", "ERROR")
            logger.log(f"Exception traceback:\n{traceback.format_exc()}", "ERROR")
            logger.log(f"Failed selector: {payload.get('selector')}", "ERROR")
        # On error, slightly penalize selector in registry
        try:
            registry = dict(state.get('selector_registry') or {})
            label_key = (action.label or '').strip().lower()
            if label_key:
                entry = registry.get(label_key) or {}
                sel = payload.get('selector') or ''
                if sel:
                    entry[sel] = int(entry.get(sel) or 0) - 1
                    registry[label_key] = entry
        except Exception:
            registry = state.get('selector_registry') or {}
        return {
            'error': str(e),
            'stuck_count': state['stuck_count'] + 1
        }


