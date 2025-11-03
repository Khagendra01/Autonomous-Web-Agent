from typing import Any, Dict, List, Optional, Tuple
import json
import os

from ..state import AgentState, ScoredAction
from ..utils.logger import get_logger
from ..utils.json_parser import extract_json_array
from .common import client


def _filter_empty_fields(element: Dict[str, Any]) -> Dict[str, Any]:
    """Filter out empty fields from an interactable element to reduce payload size.
    
    Removes:
    - Empty strings: ""
    - Empty lists: []
    - Fields with None values
    
    Keeps:
    - role, label, selector, disabled (always)
    - placeholder, type, href, tag, id, classes (only if non-empty)
    """
    filtered = {
        'role': element.get('role', ''),
        'label': element.get('label', ''),
        'selector': element.get('selector', ''),
        'disabled': element.get('disabled', False),
    }
    
    # Only add optional fields if they have meaningful values
    if element.get('placeholder'):
        filtered['placeholder'] = element['placeholder']
    if element.get('type'):
        filtered['type'] = element['type']
    if element.get('href'):
        filtered['href'] = element['href']
    if element.get('tag'):
        filtered['tag'] = element['tag']
    if element.get('id'):
        filtered['id'] = element['id']
    if element.get('classes') and len(element.get('classes', [])) > 0:
        filtered['classes'] = element['classes']
    
    return filtered


def _action_key_from_scored(action: ScoredAction) -> str:
    # Key prioritizes selector + type which best identifies a unique UI action
    return f"{action.action_type}|{action.selector}"


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


def _has_role_conflict(action: ScoredAction, all_actions: List[ScoredAction]) -> bool:
    """Check if this action has a role conflict - same label exists as both option and link.
    
    Returns True if this action is role=link and a role=option with the same label exists.
    This penalizes background links when dropdown options are available.
    """
    if 'role=link' not in action.selector:
        return False
    
    # Find if there's a role=option with the same label
    for other in all_actions:
        if other == action:
            continue
        if 'role=option' not in other.selector:
            continue
        # Check if labels match (case-insensitive, normalized)
        label_normalized = action.label.lower().strip()
        other_label_normalized = other.label.lower().strip()
        if label_normalized == other_label_normalized and label_normalized:
            return True
    return False


def _detect_destructive_action(action_label: str, action_history: List[Dict[str, Any]], goal: str) -> bool:
    """Check if an action undoes recent progress toward the goal.
    
    Returns True if the action is destructive (undoes recent progress).
    """
    if not action_history:
        return False
    
    action_label_lower = action_label.lower()
    
    # Destructive keywords that indicate undoing progress
    destructive_keywords = ['remove', 'clear', 'delete', 'undo', 'reset', 'cancel']
    if not any(keyword in action_label_lower for keyword in destructive_keywords):
        return False
    
    # Check recent actions (last 3-5) to see if we made progress toward goal
    recent_actions = action_history[-5:]
    goal_lower = goal.lower()
    
    # Check if recent actions show progress toward goal
    progress_keywords = []
    if 'filter' in goal_lower or 'inprogress' in goal_lower:
        progress_keywords = ['filter', 'in progress', 'inprogress', 'status']
    if 'create' in goal_lower or 'new' in goal_lower:
        progress_keywords.extend(['create', 'new', 'add'])
    if 'assign' in goal_lower:
        progress_keywords.extend(['assign', 'assignee'])
    if 'status' in goal_lower or 'change' in goal_lower:
        progress_keywords.extend(['status', 'change', 'done', 'progress'])
    
    # Check if any recent action shows progress
    made_progress = False
    for action in recent_actions:
        action_text = (action.get('label', '') + ' ' + action.get('text', '')).lower()
        if any(keyword in action_text for keyword in progress_keywords):
            made_progress = True
            break
    
    # If we made progress and this action is destructive, it's likely undoing progress
    return made_progress


def _build_dynamic_context_hints(state: AgentState, interactables: List[Dict[str, Any]]) -> str:
    """Build dynamic context hints based on current state (Option 6: dynamic prompting)."""
    hints = []
    action_history = state.get('action_history') or []
    errors = state.get('errors') or []
    step_count = state.get('step_count', 0)
    goal = state.get('goal', '')
    
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
    
    # Context: Combobox validation workflow detection
    if action_history:
        last_action = action_history[-1]
        if last_action.get('type') == 'type':
            typed_text = last_action.get('text', '').strip()
            last_label = last_action.get('label', '')
            
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
    
    # Context: Stay on detail_view for status changes
    if action_history:
        last_action = action_history[-1]
        last_url = last_action.get('url', '')
        current_url = state.get('current_url', '')
        
        # Check if we're on a detail view after clicking an issue/item
        # Look for URL patterns that indicate detail view (not list view)
        is_detail_view = (
            '/issue/' in current_url or 
            '/item/' in current_url or
            '/detail/' in current_url or
            # Check if URL has ID pattern (e.g., /issues/123, /task/abc-def)
            any(pattern in current_url for pattern in ['/issue/', '/task/', '/project/', '/item/'])
        )
        
        # Check if goal requires status change and we're on detail view
        goal_lower = goal.lower()
        requires_status_change = (
            'status' in goal_lower or 
            'change' in goal_lower or 
            'done' in goal_lower or
            'complete' in goal_lower
        )
        
        # Check sub-tasks for status_change type
        sub_tasks = state.get('sub_tasks') or []
        has_status_task = any(
            task.get('type') == 'status_change' 
            for task in sub_tasks
        )
        
        if is_detail_view and (requires_status_change or has_status_task):
            hints.append("📍 STAY ON CURRENT CONTEXT: You are on a detail view after selecting an item. Status changes should be performed HERE on this page. Do NOT navigate back to list view - look for status controls on this page (score 8-10 for status-related actions on this page, score 2-4 for navigation back to list).")
    
    return '\n'.join(hints) if hints else ""


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions are most likely to advance the goal (app-agnostic)."""
    logger = get_logger()
    goal = state.get('goal', '')
    step = state.get('step_count', 0)
    if logger:
        logger.log(f"Analyzing actions for goal: {goal}", "INFO")

    if logger:
        logger.log_section(f"SCORE - Step {step}")
        logger.log(f"Goal: {goal}")

    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4.1"
    max_elements = int(state.get('scoring_max_elements') or 80)

    # Prepare context for LLM – salience-based selection and stratified sampling
    interactables_full = state.get('interactable_elements') or []

    # Heuristic salience score: enabled > role priority > goal keyword match > selector memory
    goal_text = (state.get('goal') or state.get('instruction') or '').lower()
    goal_terms = [t for t in (goal_text.replace(',', ' ').split()) if len(t) >= 3][:6]
    selector_registry = state.get('selector_registry') or {}
    role_priority = {
        'button': 4,
        'option': 4,
        'menuitem': 4,
        'combobox': 3,
        'textbox': 3,
        'link': 2,
    }

    def _salience(elem: Dict[str, Any]) -> float:
        role = (elem.get('role') or '').lower()
        label = (elem.get('label') or '').lower()
        disabled = bool(elem.get('disabled', False))
        base = 0.0
        base += 2.0 if not disabled else 0.0
        base += float(role_priority.get(role, 1))
        if label and goal_terms:
            matches = sum(1 for t in goal_terms if t in label)
            base += min(2.0, 0.5 * matches)
        # Slight boost if we have selector memory for this label
        if label and isinstance(selector_registry, dict) and selector_registry.get(label):
            base += 0.8
        return base

    # Stratified quotas by role type (adjusted by available max)
    quotas_default = {
        'button': 30,
        'option': 25,
        'menuitem': 12,
        'combobox': 8,
        'textbox': 12,
        'link': 10,
    }
    # Allow config override
    quotas = dict(quotas_default)
    try:
        custom = state.get('scoring_role_quotas') or {}
        if isinstance(custom, dict):
            quotas.update({str(k).lower(): int(v) for k, v in custom.items()})
    except Exception:
        pass

    # Bucketize and sort by salience within each bucket
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in interactables_full:
        r = (e.get('role') or '').lower()
        buckets.setdefault(r, []).append(e)
    for r, items in buckets.items():
        try:
            items.sort(key=_salience, reverse=True)
        except Exception:
            pass

    # Fill selection honoring quotas, then backfill remaining capacity by global salience
    selected: List[Dict[str, Any]] = []
    remaining_cap = max_elements
    for r, q in quotas.items():
        if remaining_cap <= 0:
            break
        chunk = buckets.get(r, [])[:min(q, remaining_cap)]
        if chunk:
            selected.extend(chunk)
            remaining_cap -= len(chunk)

    if remaining_cap > 0:
        # Backfill from any role, highest salience, excluding already picked
        seen_ids = set(id(x) for x in selected)
        rest = [e for role_items in buckets.values() for e in role_items if id(e) not in seen_ids]
        try:
            rest.sort(key=_salience, reverse=True)
        except Exception:
            pass
        selected.extend(rest[:remaining_cap])

    interactables = selected[:max_elements]

    # Fingerprint-based cache: reuse previous scored_actions if nothing changed
    current_fp = state.get('interactable_fingerprint') or ""
    last_fp = state.get('last_scoring_fingerprint') or ""
    cached_actions = state.get('scored_actions') or []
    cache_ttl_steps = int(state.get('scoring_cache_ttl_steps') or 1)
    last_scored_step = int(state.get('last_scored_step') or -9999)
    if current_fp and last_fp and current_fp == last_fp:
        if cached_actions and (step - last_scored_step) <= cache_ttl_steps:
            if logger:
                logger.log("Reusing cached scored_actions (interactables unchanged)", "INFO")
            return {
                'scored_actions': cached_actions,
                'next_action': None,
                'last_scoring_fingerprint': current_fp,
                'last_scored_step': step,
            }

    # If selector memory exists for an element's label, prefer the best-known selector
    def _best_selector_for_label(lbl: str) -> Optional[str]:
        try:
            entry = selector_registry.get((lbl or '').lower()) or {}
            if not isinstance(entry, dict) or not entry:
                return None
            # choose selector with highest success count
            return max(entry.items(), key=lambda kv: int(kv[1] or 0))[0]
        except Exception:
            return None

    for e in interactables:
        try:
            lbl = e.get('label') or ''
            best = _best_selector_for_label(lbl)
            if best:
                e['selector'] = best
        except Exception:
            pass

    # Filter out empty fields to reduce payload size
    filtered_interactables = [_filter_empty_fields(elem) for elem in interactables]

    if logger:
        logger.log(f"Analyzing {len(interactables)} interactable elements (from {len(interactables_full)} total)")
        # Log breakdown by role for transparency
        try:
            role_counts = {}
            for e in interactables:
                r = (e.get('role') or '').lower()
                role_counts[r] = role_counts.get(r, 0) + 1
            logger.log_dict("Selected elements by role", role_counts)
        except Exception:
            pass

    # Build action history summary
    history_summary = []
    action_history = state.get('action_history') or []
    for i, action in enumerate(action_history[-5:]):  # Last 5 actions
        text_part = f" with text '{action.get('text')}'" if action.get('type') == 'type' and action.get('text') else ""
        history_summary.append(f"{i+1}. {action.get('type', '')} on '{action.get('label', 'N/A')}'{text_part}")

    if logger:
        logger.log_list("Recent actions (last 5)", history_summary)

    # Detect availability of status control (heuristic) to satisfy context by control presence
    status_control_available = False
    try:
        for elem in interactables_full:
            label = (elem.get('label') or '').lower()
            role = (elem.get('role') or '').lower()
            if not label:
                continue
            if any(term in label for term in ['status', 'in progress', 'done', 'to do', 'backlog', 'complete']):
                if role in ['button', 'combobox', 'menuitem', 'option']:
                    status_control_available = True
                    break
    except Exception:
        status_control_available = False

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_context_hints(state, interactables)
    
    if logger and dynamic_hints:
        logger.log("Dynamic Context Hints:", "HINT")
        logger.log(dynamic_hints, "HINT")

    # Build sub-task context for scoring
    sub_tasks = state.get('sub_tasks') or []
    current_sub_task_idx = state.get('current_sub_task_index', 0)
    current_sub_task = None
    incomplete_sub_tasks = []
    
    if sub_tasks:
        if current_sub_task_idx < len(sub_tasks):
            current_sub_task = sub_tasks[current_sub_task_idx]
        incomplete_sub_tasks = [t for t in sub_tasks if t.get('status') != 'completed']

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
{"## SUB-TASK CONTEXT (CRITICAL - READ CAREFULLY)" + chr(10) + f"Active Sub-Task: {current_sub_task['description'] if current_sub_task else 'No sub-tasks identified'}" + chr(10) + f"Task Type: {current_sub_task['type'] if current_sub_task else 'N/A'}" + chr(10) + f"Required Context: {current_sub_task['required_context'] if current_sub_task else 'N/A'}" + chr(10) + f"Current URL: {state.get('current_url', '')}" + chr(10) + f"Context Check: Does current URL match required_context '{current_sub_task['required_context'] if current_sub_task else 'N/A'}'? Verify before scoring!" + chr(10) + chr(10) if sub_tasks else ""}
{"## INCOMPLETE SUB-TASKS" + chr(10) + json.dumps([{"description": t['description'], "type": t['type'], "required_context": t['required_context']} for t in incomplete_sub_tasks], indent=2) + chr(10) + chr(10) if incomplete_sub_tasks else ""}
# AVAILABLE INTERACTIVE ELEMENTS
{json.dumps(filtered_interactables)}

# SCORING SCALE
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Possibly useful or indirectly related
- 0-3 = Unlikely to help or wrong direction

# PRINCIPLES

## Sub-Task Prioritization (CRITICAL - ENFORCE ORDER)
{"CRITICAL: Sub-tasks must be completed in order. Violations result in severe penalties." if sub_tasks else "No sub-tasks defined - use goal alignment instead"}
{"### Active Sub-Task Scoring:" if sub_tasks else ""}
{"- Actions that DIRECTLY advance the ACTIVE sub-task (match type AND required_context AND verification patterns) = 9-10" if sub_tasks else ""}
{"- Actions that match active sub-task type but wrong context (e.g., filter action on detail_view) = MAX 4 (context mismatch penalty)" if sub_tasks else ""}
{"- Actions that skip the active sub-task to advance later sub-tasks = MAX 4 (order violation penalty)" if sub_tasks else ""}
{"### Other Sub-Tasks:" if sub_tasks else ""}
{"- Actions that advance prerequisites for active sub-task (e.g., navigation before filtering) = 5-6" if sub_tasks else ""}
{"- Actions that advance any incomplete sub-task but active is incomplete = 3-4 (active sub-task not done yet)" if sub_tasks else ""}
{"### Context Verification:" if sub_tasks else ""}
{"- REQUIRED: Verify action context matches required_context before scoring 7+" if sub_tasks else ""}
{"- Example: Filter sub-task requires list_view. Clicking filter on detail_view = 0-4, not 7+" if sub_tasks else ""}
{"- Example: If active sub-task is 'filter' requiring list_view, actions on detail_view = max 4" if sub_tasks else ""}

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

## Destructive Actions (CRITICAL - AVOID UNDOING PROGRESS)
- Actions that UNDO recent progress (e.g., "Remove filter" after filtering, "Clear" after entering data) = score 0-2
- If recent actions made progress toward the goal, destructive actions (remove/clear/delete/undo) contradict that progress → HEAVILY PENALIZE
- Example: If goal requires "filter by inprogress" and recent action was clicking filter option → "Remove filter" button = score 0-2 (not 8-9)
- Example: If goal requires "create project" and form was filled → "Cancel" button = score 0-2
- Only score destructive actions highly (7+) if they explicitly help achieve the goal (e.g., "Clear form" when goal requires starting over)

## Efficiency (IMPORTANT)
- Avoid repeating recently ineffective actions
- Prioritize goal-directed actions over exploration

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
        if logger:
            logger.log(f"Scoring LLM call failed: {e}", "ERROR")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Scoring LLM call failed: {e}",
        }

    scored_actions_raw = extract_json_array(content) or []

    parsed_actions: List[ScoredAction] = []
    for a in scored_actions_raw:
        try:
            action_label = str(a.get('label', ''))
            action_type = str(a.get('action_type'))
            selector = str(a.get('selector'))
            label = str(a.get('label', ''))
            score = float(a.get('score', 0))
            reasoning = str(a.get('reasoning', ''))
            text = a.get('text')
            
            # Check if this is a destructive action that undoes recent progress
            if _detect_destructive_action(action_label, action_history, goal):
                # Heavily penalize destructive actions (cap at 2.0)
                if score > 2.0:
                    score = 2.0
                    reasoning = f"[DESTRUCTIVE ACTION PENALTY] {reasoning} This action undoes recent progress toward the goal."
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
    
    # Post-process: Penalize role=link when role=option exists for same label
    # This prevents clicking background links when dropdown options are available
    for action in parsed_actions:
        try:
            if action.action_type == 'click' and _has_role_conflict(action, parsed_actions):
                # Penalize role=link candidates when role=option exists (cap at 4.0)
                if action.score > 4.0:
                    action.score = 4.0
                    action.reasoning = f"[ROLE CONFLICT PENALTY] {action.reasoning} A dropdown option (role=option) exists with the same label - prefer that over this background link."
        except Exception:
            continue

    # Post-process: Compose/modal strict mode – penalize background links unless intent is navigation
    try:
        active_ctx = state.get('active_context') or {}
        is_compose_active = bool(active_ctx and active_ctx.get('type') in ['form', 'dropdown', 'menu', 'active_context'])
        # Hard-coded compose-safe mode ON by default (config)
        compose_safe_mode = True
        if is_compose_active:
            navigation_terms = ['profile', 'view', 'details', 'open', 'navigate']
            for action in parsed_actions:
                try:
                    if action.action_type != 'click':
                        continue
                    sel = (action.selector or '').lower()
                    is_link = 'role=link' in sel or sel.startswith('a[') or sel.startswith('a:')
                    has_nav_intent = any(t in (action.label or '').lower() for t in navigation_terms)
                    # Email-like labels are especially risky (global profile links)
                    looks_like_email = '@' in (action.label or '')
                    if is_link and not has_nav_intent:
                        if compose_safe_mode and looks_like_email:
                            # Hard zero in safe mode to avoid accidental navigation
                            action.score = 0.0
                            action.reasoning = f"[COMPOSE SAFE MODE] {action.reasoning} Background email link disabled while compose is active."
                        elif action.score > 3.0:
                            action.score = 3.0
                            action.reasoning = f"[COMPOSE CONTEXT PENALTY] {action.reasoning} Background link penalized while compose/modal is active. Prefer in-container options first."
                except Exception:
                    continue
    except Exception:
        pass

    # Post-process: Generic prerequisite gating signal for commit-like actions when requirements unmet
    reqs = state.get('requirements') or {}
    unmet = [k for k, v in reqs.items() if v is False]
    if unmet:
        commit_terms = ['submit', 'save', 'create', 'send', 'confirm', 'done', 'finish', 'post']
        for action in parsed_actions:
            try:
                label_lower = (action.label or '').lower()
                is_commit = any(term in label_lower for term in commit_terms)
                if is_commit and action.score > 4.0:
                    action.score = 4.0
                    unmet_str = ', '.join(unmet)
                    action.reasoning = f"[PREREQUISITE GATING] {action.reasoning} Commit-like action gated until requirements met: {unmet_str}."
            except Exception:
                continue

    # Post-process: Anchor bias toward target entity
    anchor = state.get('target_entity') or {}
    anchor_id = (anchor.get('id') or '').lower()
    anchor_title = (anchor.get('title') or '').lower()
    if anchor_id or anchor_title:
        for action in parsed_actions:
            try:
                label_l = (action.label or '').lower()
                if (anchor_id and anchor_id in label_l) or (anchor_title and anchor_title and anchor_title in label_l):
                    # Boost actions that clearly operate on the anchored entity
                    if action.score < 9.0:
                        action.score = min(9.0, action.score + 2.0)
                        action.reasoning = f"[ANCHOR BOOST] {action.reasoning} Targets anchored entity ({anchor_id or anchor_title})."
            except Exception:
                continue

    # Post-process: Uncertainty reduction boost
    # If any requirement is unknown (missing key) or explicitly False, boost actions that reveal context
    # e.g., 'Open details', 'View', 'Show more', or actions opening forms/menus
    reqs_all = state.get('requirements') or {}
    has_unknowns = False
    try:
        # Unknown if key expected but not present, or any False present
        has_unknowns = (False in reqs_all.values()) or (len(reqs_all) == 0)
    except Exception:
        has_unknowns = True
    if has_unknowns:
        reveal_terms = ['open details', 'open', 'view', 'show more', 'expand', 'details']
        for action in parsed_actions:
            try:
                if action.action_type != 'click':
                    continue
                label_l = (action.label or '').lower()
                if any(t in label_l for t in reveal_terms):
                    action.score = max(action.score, 7.0)
                    action.reasoning = f"[UNCERTAINTY REDUCTION] {action.reasoning} Reveals context/state when requirements are unknown."
            except Exception:
                continue

    # Post-process: Control-availability override for status change
    # If a status control is visible/enabled, allow status actions to outrank navigation
    if status_control_available:
        for action in parsed_actions:
            try:
                label_l = (action.label or '').lower()
                is_status_action = any(term in label_l for term in ['status', 'in progress', 'done', 'to do', 'backlog', 'complete'])
                is_navigation = any(term in label_l for term in ['issues', 'active issues', 'back', 'close details'])
                if is_status_action:
                    # Ensure status actions have a strong score floor when control is available
                    if action.score < 8.5:
                        action.score = 8.5
                        action.reasoning = f"[CONTROL AVAILABLE] {action.reasoning} Status control visible; perform status change here rather than navigating."
                elif is_navigation:
                    # Slightly de-prefer broad navigation when the control we need is present
                    if action.score > 6.0:
                        action.score = 6.0
                        action.reasoning = f"[CONTROL AVAILABLE PENALTY] {action.reasoning} Navigation deprioritized because status control is already available."
            except Exception:
                continue

    # Return updated requirements so downstream nodes can gate decisions by predicates
    requirements = dict(state.get('requirements') or {})
    requirements['statusControlAvailable'] = bool(status_control_available)

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

    if logger:
        logger.log(f"Scored {len(adjusted)} actions (deduped)", "INFO")
        for i, action in enumerate(adjusted[:3]):
            logger.log(f"{i+1}. [{action.score:.1f}] {action.action_type} '{action.label}' - {action.reasoning}", "INFO")

    if logger:
        logger.log(f"Scored {len(adjusted)} actions (deduped)")
        top_actions = adjusted[:5]
        for i, action in enumerate(top_actions, 1):
            logger.log(f"{i}. [{action.score:.1f}] {action.action_type} '{action.label}' - selector: {action.selector}", "SCORE")
            if action.action_type == 'type' and action.text:
                logger.log(f"   Text to type: '{action.text}'", "SCORE")
        if len(adjusted) > 1:
            top_score = adjusted[0].score
            same_group = [a for a in adjusted if a.score >= top_score - 1.0][:8]
            if same_group and len(same_group) > 1:
                logger.log("Same-score group (±1.0 from top):", "SCORE")
                for a in same_group[:5]:
                    suffix = f" → type text='{a.text}'" if (a.action_type == 'type' and a.text) else ""
                    logger.log(f"  - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix} - selector: {a.selector}", "SCORE")

    return {
        'scored_actions': adjusted,
        'next_action': None,
        'last_scoring_fingerprint': current_fp,
        'last_scored_step': step,
    }


