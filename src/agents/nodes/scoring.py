from typing import Any, Dict, List, Optional, Tuple
import json
import re

from ..state import AgentState, ScoredAction
from ..utils.dom import summarize_accessibility_tree
from ..utils.logger import get_logger
from ...drivers.utils.selector_normalizer import is_placeholder_text
from .common import client


def _action_key_from_scored(action: ScoredAction) -> str:
    # Key prioritizes selector + type which best identifies a unique UI action
    return f"{action.action_type}|{action.selector}"


def _extract_json_array(text: str) -> Optional[List[Any]]:
    # Strip fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()
    # Direct
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    # Regex fallback: find first bracketed array
    try:
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            obj = json.loads(match.group(0))
            if isinstance(obj, list):
                return obj
    except Exception:
        return None
    return None


def _detect_active_context(
    state: AgentState, 
    interactables: List[Dict[str, Any]]
) -> Tuple[Optional[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Detect if we're in an active context (form/modal/dropdown) after a context-changing action.
    Returns: (context_type, context_elements, background_elements)
    - context_type: 'form', 'dropdown', 'menu', or None
    - context_elements: Elements that belong to the active context
    - background_elements: Elements from the page behind the context
    """
    action_history = state.get('action_history', [])
    if not action_history:
        return None, [], []
    
    last_action = action_history[-1]
    last_label = last_action.get('label', '').lower()
    last_action_type = last_action.get('type', '')
    
    # Check if context should expire
    active_context_info = state.get('active_context')
    if active_context_info:
        context_step_count = active_context_info.get('step_count', 0)
        current_step = state.get('step_count', 0)
        # Expire after 3 steps
        if current_step - context_step_count >= 3:
            return None, [], []
    
    # Pattern 1: Context-changing button/link labels
    context_triggers = ['create', 'message', 'new', 'add', 'compose', 'open', 'edit', 'write']
    is_context_action = (
        last_action_type == 'click' and 
        any(trigger in last_label for trigger in context_triggers)
    )
    
    # Pattern 2: Element count surge (indicates new UI opened)
    prev_count = state.get('prev_interactable_count', 0)
    current_count = len(interactables)
    element_surge = current_count > prev_count + 10  # Threshold: +10 new elements
    
    # Pattern 3: Check for combobox/dropdown interaction
    is_dropdown_action = (
        last_action_type == 'click' and
        any(term in last_label.lower() for term in ['select', 'choose', 'pick', 'dropdown'])
    )
    
    # Conservative detection: require at least one strong signal
    if not (is_context_action or element_surge or is_dropdown_action):
        return None, [], []
    
    # Identify context-relevant elements based on semantic patterns
    context_elements = []
    background_elements = []
    
    for elem in interactables:
        role = elem.get('role', '').lower()
        label = (elem.get('label') or '').lower()
        placeholder = (elem.get('placeholder') or '').lower()
        elem_id = (elem.get('id') or '').lower()
        elem_classes = ' '.join(elem.get('classes', [])).lower()
        
        # Heuristic 1: Form-related elements (for forms/modals)
        is_form_element = False
        is_form_related = False
        
        if role in ['textbox', 'combobox']:
            # Check if it's a form input with relevant labels/placeholders
            form_keywords = [
                'recipient', 'to', 'subject', 'message', 'body', 'content',
                'title', 'name', 'email', 'from', 'cc', 'bcc',
                'type the name', 'add subject', 'edit message', 'compose',
                'enter', 'write', 'input'
            ]
            combined_text = f"{label} {placeholder} {elem_id} {elem_classes}"
            is_form_element = any(keyword in combined_text for keyword in form_keywords)
            
            # Also check for common form field patterns
            if placeholder and ('type' in placeholder or 'add' in placeholder or 'enter' in placeholder):
                is_form_related = True
        
        # Heuristic 2: Submit/action buttons within context
        is_submit_button = False
        if role == 'button':
            submit_keywords = ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish']
            is_submit_button = any(keyword in label for keyword in submit_keywords)
        
        # Heuristic 3: Dropdown options (for dropdown context)
        is_dropdown_option = role == 'option'
        
        # Heuristic 4: Menu items (for menu context)
        is_menu_item = role in ['menuitem', 'menuitemcheckbox', 'menuitemradio']
        
        # Determine if element is context-relevant
        if is_form_element or is_form_related or is_submit_button:
            # Form context
            if is_context_action or element_surge:
                context_elements.append(elem)
            else:
                background_elements.append(elem)
        elif is_dropdown_option and is_dropdown_action:
            # Dropdown context
            context_elements.append(elem)
        elif is_menu_item:
            # Menu context
            context_elements.append(elem)
        else:
            # Everything else is background
            background_elements.append(elem)
    
    # Determine context type
    if context_elements:
        if any(elem.get('role', '').lower() in ['textbox', 'combobox'] for elem in context_elements):
            context_type = 'form'
        elif any(elem.get('role', '').lower() == 'option' for elem in context_elements):
            context_type = 'dropdown'
        elif any(elem.get('role', '').lower() in ['menuitem', 'menuitemcheckbox'] for elem in context_elements):
            context_type = 'menu'
        else:
            context_type = 'active_context'
        
        return context_type, context_elements, background_elements
    
    return None, [], []


def _build_dynamic_context_hints(state: AgentState, interactables: List[Dict[str, Any]]) -> str:
    """Build dynamic context hints based on current state (Option 6: dynamic prompting)."""
    hints = []
    action_history = state.get('action_history') or []
    errors = state.get('errors') or []
    step_count = state.get('step_count', 0)
    
    # Context: Active context detection (form/modal/dropdown)
    context_type, context_elements, background_elements = _detect_active_context(state, interactables)
    if context_type:
        last_action = action_history[-1] if action_history else {}
        last_label = last_action.get('label', 'N/A')
        
        # Build context hint with element counts and guidance
        context_elem_count = len(context_elements)
        bg_elem_count = len(background_elements)
        
        if context_type == 'form':
            hints.append(
                f"🎯 ACTIVE CONTEXT: After clicking '{last_label}', a {context_type} opened with {context_elem_count} form-related elements. "
                f"Elements that belong to this form (inputs, submit buttons) should be prioritized with +2-3 score boost. "
                f"Background elements from the page ({bg_elem_count} elements like navigation links, dashboard widgets) should be deprioritized with -2-3 penalty. "
                f"Focus on completing the form workflow before interacting with background elements."
            )
        elif context_type == 'dropdown':
            hints.append(
                f"🎯 ACTIVE CONTEXT: A {context_type} is open with {context_elem_count} options. "
                f"Prioritize selecting from these options (+2-3 boost) over background elements ({bg_elem_count} elements, -2-3 penalty)."
            )
        elif context_type == 'menu':
            hints.append(
                f"🎯 ACTIVE CONTEXT: A {context_type} is open with {context_elem_count} menu items. "
                f"Prioritize menu selections (+2-3 boost) over background elements ({bg_elem_count} elements, -2-3 penalty)."
            )
        else:
            hints.append(
                f"🎯 ACTIVE CONTEXT: New UI context opened ({context_elem_count} context elements, {bg_elem_count} background elements). "
                f"Prioritize context elements (+2-3 boost) over background (-2-3 penalty)."
            )
        
        # Update state to track active context for lifecycle management
        state['active_context'] = {
            'type': context_type,
            'step_count': step_count,
            'last_action_label': last_label
        }
    elif state.get('active_context'):
        # Context was previously active but is no longer detected - clear it
        # This happens when the form/modal was closed
        state['active_context'] = None
    
    # Context: Error resolution priority
    if errors:
        error_summary = ', '.join(str(e)[:50] for e in errors[:3])
        hints.append(f"⚠️ CRITICAL: Validation errors detected: {error_summary}. Prioritize actions that resolve these errors (score 8-10 for error-fixing actions, 0-3 for actions blocked by errors).")
    
    # Context: Early stage exploration
    if step_count < 3:
        hints.append("🔍 EARLY STAGE: Task just started. Include exploration actions (scroll, open menus) to discover available options. Score exploration actions 4-6 even if not directly goal-related.")
    
    # Context: Combobox validation workflow detection
    if action_history:
        last_action = action_history[-1]
        if last_action.get('type') == 'type':
            typed_text = last_action.get('text', '').strip().lower()
            last_label = last_action.get('label', '').lower()
            
            # Check if we typed into a combobox field (or email/recipient field that behaves like combobox)
            is_combobox_field = (
                'combobox' in last_label or
                'type the name' in last_label or
                'recipient' in last_label or
                'to' in last_label or
                'email' in last_label or  # Email fields often have dropdown options
                'address' in last_label or  # Email addresses field
                'invite' in last_label or  # Invite fields
                any(elem.get('role') == 'combobox' and 
                    (last_label in (elem.get('label') or '').lower() or 
                     last_label in (elem.get('placeholder') or '').lower())
                    for elem in interactables) or
                # Also check if field has combobox-like behavior (shows dropdown after typing)
                any(elem.get('role') in ['textbox', 'combobox'] and 
                    last_label in (elem.get('label') or '').lower() and
                    any(keyword in (elem.get('placeholder') or '').lower() for keyword in 
                        ['email', 'recipient', 'to', 'invite', 'type', 'add', 'enter'])
                    for elem in interactables)
            )
            
            if typed_text and is_combobox_field:
                # Temporal detection: Find elements that appeared AFTER typing
                # Compare current elements with previous observation to find newly appeared elements
                prev_elements = state.get('prev_interactable_elements') or []
                prev_selectors = {elem.get('selector', '') for elem in prev_elements}
                
                # Find newly appeared elements (these are the dropdown options)
                newly_appeared = [
                    elem for elem in interactables
                    if elem.get('selector', '') not in prev_selectors
                ]
                
                # Find ALL newly appeared dropdown options (not just matching typed text)
                # Sometimes options appear that don't exactly match (e.g., "Invite: email")
                all_newly_appeared_options = [
                    elem for elem in interactables
                    if elem.get('role') == 'option' and 
                    elem.get('selector', '') not in prev_selectors
                ]
                
                # Check for dropdown options matching typed text
                matching_options = [
                    elem for elem in interactables
                    if elem.get('role') == 'option' and 
                    (typed_text in (elem.get('label') or '').lower() or 
                     (elem.get('label') or '').lower() in typed_text or
                     # Also match if option contains typed email
                     any(part in (elem.get('label') or '').lower() for part in typed_text.split('@') if '@' in typed_text and len(part) > 2))
                ]
                
                # Identify which matching options are newly appeared vs existing
                newly_appeared_options = [
                    opt for opt in matching_options
                    if opt.get('selector', '') not in prev_selectors
                ]
                
                # If no matching options but we have newly appeared options, use those
                # This handles cases where option is "Invite: email" instead of just "email"
                if not newly_appeared_options and all_newly_appeared_options:
                    # Use all newly appeared options, prioritize first one
                    newly_appeared_options = all_newly_appeared_options
                
                existing_elements_with_label = [
                    elem for elem in interactables
                    if elem.get('selector', '') in prev_selectors and
                    (typed_text in (elem.get('label') or '').lower() or 
                     (elem.get('label') or '').lower() in typed_text)
                ]
                
                # Check if submit/send button is disabled (indicates validation needed)
                has_disabled_submit = any(
                    (elem.get('role') == 'button' or elem.get('role') == 'link') and
                    elem.get('disabled', False) and
                    any(term in (elem.get('label') or '').lower() for term in 
                        ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish', 'invite'])
                    for elem in interactables
                )
                
                # Filter out placeholder text from options
                # Placeholder text like "name@gmail.com" shouldn't be selected
                options_to_use = newly_appeared_options if newly_appeared_options else (matching_options if matching_options else all_newly_appeared_options)
                
                # Filter out placeholder/example text options
                if options_to_use:
                    filtered_options = [
                        opt for opt in options_to_use
                        if not is_placeholder_text(opt.get('label', ''))
                    ]
                    # Only use filtered if we still have options, otherwise keep original
                    if filtered_options:
                        options_to_use = filtered_options
                    
                    # Also check for placeholder text in other interactables and warn about it
                    placeholder_elements = [
                        elem for elem in interactables
                        if is_placeholder_text(elem.get('label', ''))
                    ]
                    if placeholder_elements:
                        placeholder_labels = [elem.get('label', 'N/A') for elem in placeholder_elements[:2]]
                        # Add warning to hints
                        hints.append(
                            f"⚠️ WARNING: Placeholder/example text detected ({', '.join(placeholder_labels)}) - these are NOT real options. "
                            f"Score placeholder elements 0-1. Do NOT select placeholder text."
                        )
                
                if options_to_use:
                    # Temporal logic: Elements that appeared AFTER typing are dropdown options
                    # Elements that existed BEFORE typing are background page elements
                    
                    # Sort options by order (preserve order from interactables list = DOM order)
                    # This ensures first option is prioritized
                    options_with_order = []
                    for opt in options_to_use:
                        try:
                            idx = next(i for i, elem in enumerate(interactables) if elem.get('selector') == opt.get('selector'))
                            options_with_order.append((idx, opt))
                        except StopIteration:
                            options_with_order.append((999, opt))  # If not found, put at end
                    options_sorted = [opt for _, opt in sorted(options_with_order)]
                    
                    # First option is the primary/default selection
                    first_option = options_sorted[0] if options_sorted else None
                    first_option_label = first_option.get('label', 'N/A') if first_option else 'N/A'
                    first_option_selector = first_option.get('selector', 'N/A') if first_option else 'N/A'
                    other_options = options_sorted[1:3] if len(options_sorted) > 1 else []
                    
                    option_labels = [opt.get('label', 'N/A') for opt in options_sorted[:3]]
                    option_selectors = [opt.get('selector', 'N/A') for opt in options_sorted[:3]]
                    existing_labels = [elem.get('label', 'N/A') for elem in existing_elements_with_label[:3]] if existing_elements_with_label else []
                    
                    if has_disabled_submit:
                        if first_option:
                            hints.append(
                                f"🔗 COMBOBOX VALIDATION REQUIRED: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                                f"The FIRST option '{first_option_label}' (selector: {first_option_selector}) is the PRIMARY/DEFAULT selection - score it 9-10. "
                                f"{f'Other options ({[opt.get("label") for opt in other_options]}) are alternatives - score them 7-8. ' if other_options else ''}"
                                f"{f'Background elements with similar labels ({existing_labels}) existed before typing - these are page links, NOT dropdown options. ' if existing_labels else ''}"
                                f"The Submit/Send/Invite button is DISABLED until you select one of the NEWLY APPEARED dropdown options. "
                                f"Score the FIRST option '{first_option_label}' 9-10. Score other newly appeared options 7-8. "
                                f"Score background elements that existed before typing 0-2."
                            )
                        else:
                            hints.append(
                                f"🔗 COMBOBOX VALIDATION REQUIRED: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                                f"These options (selectors: {', '.join(option_selectors[:2])}) are NEWLY APPEARED and are the dropdown options to select. "
                                f"{f'Background elements with similar labels ({existing_labels}) existed before typing - these are page links, NOT dropdown options. ' if existing_labels else ''}"
                                f"The Submit/Send/Invite button is DISABLED until you select one of the NEWLY APPEARED dropdown options. "
                                f"Score NEWLY APPEARED options (selectors: {', '.join(option_selectors[:2])}) 8-9. "
                                f"Score background elements that existed before typing 0-2."
                            )
                    else:
                        if first_option:
                            hints.append(
                                f"🔗 COMBOBOX SELECTION: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                                f"The FIRST option '{first_option_label}' (selector: {first_option_selector}) is the PRIMARY/DEFAULT selection - score it 9-10. "
                                f"{f'Other options ({[opt.get("label") for opt in other_options]}) are alternatives - score them 7-8. ' if other_options else ''}"
                                f"{f'Background elements ({existing_labels}) with similar labels existed before - these are page links, NOT the dropdown. ' if existing_labels else ''}"
                                f"Select the FIRST option '{first_option_label}' to validate the input. "
                                f"Score the FIRST option 9-10. Score other newly appeared options 7-8. Score background elements that existed before typing 0-2."
                            )
                        else:
                            hints.append(
                                f"🔗 COMBOBOX SELECTION: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                                f"These options (selectors: {', '.join(option_selectors[:2])}) are NEWLY APPEARED after your typing action. "
                                f"{f'Background elements ({existing_labels}) with similar labels existed before - these are page links, NOT the dropdown. ' if existing_labels else ''}"
                                f"Select one of the NEWLY APPEARED dropdown options to validate the input. "
                                f"Score NEWLY APPEARED options 8-9. Score background elements that existed before typing 0-2."
                            )
                elif matching_options:
                    # Fallback: We have matching options but couldn't determine which are new
                    option_labels = [opt.get('label', 'N/A') for opt in matching_options[:3]]
                    option_selectors = [opt.get('selector', 'N/A') for opt in matching_options[:3]]
                    if has_disabled_submit:
                        hints.append(
                            f"🔗 COMBOBOX VALIDATION: Dropdown options matching '{typed_text}' appeared: {', '.join(option_labels)}. "
                            f"Score dropdown options (role='option', selectors: {', '.join(option_selectors[:2])}) 8-9. "
                            f"Penalize background elements (role='link'/'button') with similar labels."
                        )
                    else:
                        hints.append(
                            f"🔗 COMBOBOX SELECTION: Select dropdown option matching '{typed_text}' (selectors: {', '.join(option_selectors[:2])}) to validate input. "
                            f"Score options (role='option') 8-9, penalize background links."
                        )
    
    # Context: Goal completion indicators
    # Check if there are high-priority submission/confirmation buttons
    has_submit_buttons = any(
        'submit' in (elem.get('label') or '').lower() or
        'confirm' in (elem.get('label') or '').lower() or
        'send' in (elem.get('label') or '').lower() or
        elem.get('role') in ['button', 'link'] and 
        any(term in (elem.get('label') or '').lower() for term in ['done', 'complete', 'finish', 'save'])
        for elem in interactables
    )
    if has_submit_buttons and step_count > 5:
        hints.append("✅ COMPLETION READY: Submission/confirmation controls detected. If goal-aligned actions are complete, prioritize these controls (score 9-10).")
    
    return '\n'.join(hints) if hints else ""


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions are most likely to advance the goal (app-agnostic)."""
    logger = get_logger()
    goal = state.get('goal', '')
    step = state.get('step_count', 0)
    print(f"\n[SCORE] Analyzing actions for goal: {goal}")

    if logger:
        logger.log_section(f"SCORE - Step {step}")
        logger.log(f"Goal: {goal}")

    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4o"
    max_elements = int(state.get('scoring_max_elements') or 80)

    # Prepare context for LLM
    dom_summary = summarize_accessibility_tree(state.get('dom_snapshot') or {})
    interactables_full = state.get('interactable_elements') or []
    interactables = interactables_full[:max_elements]

    if logger:
        logger.log(f"Analyzing {len(interactables)} interactable elements (from {len(interactables_full)} total)")

    # Build action history summary
    history_summary = []
    action_history = state.get('action_history') or []
    for i, action in enumerate(action_history[-5:]):  # Last 5 actions
        text_part = f" with text '{action.get('text')}'" if action.get('type') == 'type' and action.get('text') else ""
        history_summary.append(f"{i+1}. {action.get('type', '')} on '{action.get('label', 'N/A')}'{text_part}")

    if logger:
        logger.log_list("Recent actions (last 5)", history_summary)

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_context_hints(state, interactables)
    
    if logger and dynamic_hints:
        logger.log("Dynamic Context Hints:", "HINT")
        logger.log(dynamic_hints, "HINT")

    # Build structured prompt with clear sections (Option 2)
    prompt = f"""# ROLE & OBJECTIVE
You are an autonomous web agent's scoring module. Your task is to evaluate interactive UI elements and score them (0-10) based on how likely they are to help achieve the user's goal.

# CONTEXT
Goal: {state.get('goal', '')}
Instruction: {state.get('instruction', '')}
Current URL: {state.get('current_url', '')}
Step Count: {state.get('step_count', 0)}

Recent Actions (last 5):
{chr(10).join(history_summary) if history_summary else "None"}

{"## DYNAMIC CONTEXT HINTS" + chr(10) + dynamic_hints + chr(10) if dynamic_hints else ""}
# AVAILABLE INTERACTIVE ELEMENTS
{json.dumps(interactables, indent=2)}

# SCORING SCALE
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Possibly useful or indirectly related
- 0-3 = Unlikely to help or wrong direction

# PRINCIPLES

## Goal Alignment (CRITICAL)
- Prefer elements whose labels/roles semantically match goal terms
- Consider aria-label, placeholder, title, and visible text when matching
- If goal requires data entry, prioritize relevant input fields
- If submission is clearly required and ready, prioritize submission controls

## Safety & Feasibility (CRITICAL)
- Disabled elements (disabled=true) are not actionable → score 0-2
- Prefer enabling steps before attempting disabled actions
- If validation errors exist, prioritize actions that resolve them (see Dynamic Context Hints above)
- If Submit/Send button is disabled, look for the enabling action (e.g., selecting dropdown option after typing in combobox) rather than clicking disabled button

## Efficiency & Exploration (IMPORTANT)
- If no strong candidates exist, include low-risk exploration (scroll, open menu) to reveal options
- Avoid repeating recently ineffective actions
- Balance goal-directed actions with necessary exploration

## Selector Requirements (CRITICAL)
- Use a single, specific selector (no commas)
- Prefer role-based selectors: role=button[name="…"], role=textbox[name="…"]
- Selectors must be unique and actionable

# OUTPUT FORMAT
Return ONLY a JSON array of objects:
[
  {{
    "selector": "role=button[name=\"…\"]",
    "label": "…",
    "action_type": "click|type|scroll",
    "text": "optional text for type actions",
    "score": 0-10,
    "reasoning": "brief explanation of why this score"
  }}
]

Ensure each scored action has a valid selector, action_type, and clear reasoning."""
    
    system_message = """You are an autonomous web agent's action scoring module. Your role is to evaluate UI elements and assign scores (0-10) based on their utility toward achieving the user's goal. You must return only valid JSON arrays, following the structured scoring principles provided."""
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  Scoring LLM call failed: {e}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Scoring LLM call failed: {e}",
        }

    scored_actions_raw = _extract_json_array(content) or []

    parsed_actions: List[ScoredAction] = []
    for a in scored_actions_raw:
        try:
            action_type = str(a.get('action_type'))
            selector = str(a.get('selector'))
            label = str(a.get('label', ''))
            score = float(a.get('score', 0))
            reasoning = str(a.get('reasoning', ''))
            text = a.get('text')
            if not action_type or not selector:
                continue
            parsed_actions.append(
                ScoredAction(
                    action_type=action_type,
                    selector=selector,
                    label=label,
                    score=score,
                    reasoning=reasoning,
                    text=text,
                )
            )
        except Exception:
            continue

    # Deduplicate by action_type|selector key, keeping the highest-scored instance
    unique_by_key: Dict[str, ScoredAction] = {}
    for a in parsed_actions:
        k = _action_key_from_scored(a)
        existing = unique_by_key.get(k)
        if existing is None or a.score > existing.score:
            unique_by_key[k] = a

    deduped: List[ScoredAction] = list(unique_by_key.values())

    # Sort by score descending
    adjusted: List[ScoredAction] = sorted(deduped, key=lambda x: float(x.score or 0.0), reverse=True)

    print(f"  Scored {len(adjusted)} actions (deduped)")
    for i, action in enumerate(adjusted[:3]):
        print(f"  {i+1}. [{action.score:.1f}] {action.action_type} '{action.label}' - {action.reasoning}")

    if adjusted:
        top_score = adjusted[0].score
        same_group = [a for a in adjusted if a.score >= top_score - 1.0][:8]
        if len(same_group) > 1:
            print("  Same-score group (±1.0 from top):")
            for a in same_group:
                suffix = f" → type text='{a.text}'" if (a.action_type == 'type' and a.text) else ""
                print(f"    - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix}")
    
    if logger:
        logger.log(f"Scored {len(adjusted)} actions (deduped)")
        top_actions = adjusted[:5]
        for i, action in enumerate(top_actions, 1):
            logger.log(f"{i}. [{action.score:.1f}] {action.action_type} '{action.label}' - selector: {action.selector}", "SCORE")
            if action.action_type == 'type' and action.text:
                logger.log(f"   Text to type: '{action.text}'", "SCORE")
        if same_group and len(same_group) > 1:
            logger.log("Same-score group (±1.0 from top):", "SCORE")
            for a in same_group[:5]:
                suffix = f" → type text='{a.text}'" if (a.action_type == 'type' and a.text) else ""
                logger.log(f"  - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix} - selector: {a.selector}", "SCORE")

    return {
        'scored_actions': adjusted,
        'next_action': None,
    }


