from typing import Any, Dict, List, Optional, Tuple
import json
import os

from ..state import AgentState, ScoredAction
from ..utils.logger import get_logger
from ..utils.json_parser import extract_json_array
from .common import client
from ..knowledge.roles import ACTIONABLE_ROLES


def _summarize_instruction(text: str, max_len: int = 80) -> str:
    """Extract meaningful text from instruction/goal for typing actions.
    Tries to extract quoted titles (e.g., 'Make Web Agent B') from goals.
    Also handles unquoted titles like "Write a new issue Make Web Agent B to project...".
    """
    s = (text or "").strip().splitlines()[0]
    import re
    
    # Pattern 1: Try to extract quoted title from goal (e.g., "titled 'Make Web Agent B'")
    quoted_patterns = [
        r"titled\s+['\"]([^'\"]+)['\"]",
        r"title\s+['\"]([^'\"]+)['\"]",
        r"['\"]([^'\"]{3,50})['\"]",  # Any quoted string 3-50 chars
    ]
    for pattern in quoted_patterns:
        match = re.search(pattern, s, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            if 3 <= len(extracted) <= max_len:
                return extracted
    
    # Pattern 2: Extract unquoted titles from common patterns
    # "Write a new issue Make Web Agent B to project..." -> "Make Web Agent B"
    # "Create issue X to Y" -> "X"
    # "Make X" -> "X"
    unquoted_patterns = [
        r"(?:write|create|add|make|new)\s+(?:a\s+)?(?:new\s+)?(?:issue|task|item|note|message|post)\s+(?:titled\s+)?([A-Z][^to]+?)(?:\s+to\s+|\s+in\s+|\s+project|\s+and\s+assign|$)",  # "Write a new issue Make Web Agent B to project"
        r"(?:write|create|add|make)\s+(?:a\s+)?(?:new\s+)?([A-Z][^to]+?)(?:\s+to\s+|\s+in\s+|\s+project|\s+and\s+assign|$)",  # "Make Web Agent B to project"
        r"issue\s+(?:titled\s+)?([A-Z][^to]+?)(?:\s+to\s+|\s+in\s+|\s+project|\s+and\s+assign|$)",  # "issue Make Web Agent B to"
    ]
    
    for pattern in unquoted_patterns:
        match = re.search(pattern, s, re.IGNORECASE)
        if match:
            extracted = match.group(1).strip()
            # Clean up trailing punctuation and common words
            extracted = re.sub(r'[,\-\.]+$', '', extracted).strip()
            # Remove common trailing words that aren't part of the title
            extracted = re.sub(r'\s+(to|in|project|assign|and|the)\s*$', '', extracted, flags=re.IGNORECASE).strip()
            if 3 <= len(extracted) <= max_len:
                return extracted
    
    # Pattern 3: Extract capitalized phrase after verbs (fallback for simple cases)
    # "Create X Y Z" where X Y Z starts with capital
    simple_pattern = r"(?:write|create|add|make|new)\s+([A-Z][A-Za-z\s]{2,30}?)(?:\s+to\s+|\s+in\s+|\s+project|\s+and\s+assign|$)"
    match = re.search(simple_pattern, s, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
        extracted = re.sub(r'[,\-\.]+$', '', extracted).strip()
        extracted = re.sub(r'\s+(to|in|project|assign|and|the)\s*$', '', extracted, flags=re.IGNORECASE).strip()
        if 3 <= len(extracted) <= max_len:
            return extracted
    
    # Fallback: return first line truncated (but try to avoid common instruction words)
    fallback = (s[:max_len]).strip()
    # Remove common instruction prefixes
    fallback = re.sub(r'^(?:write|create|add|make|new)\s+(?:a\s+)?(?:new\s+)?(?:issue|task|item|note|message|post)\s+', '', fallback, flags=re.IGNORECASE)
    if len(fallback.strip()) >= 3:
        return fallback.strip()[:max_len]
    return (s[:max_len]).strip()


def _count_textboxes(items: List[Dict[str, Any]]) -> int:
    count = 0
    for e in items:
        role = (e.get('role') or '').lower()
        if role in ('textbox', 'searchbox'):
            count += 1
        elif role == 'combobox' and (e.get('placeholder') or e.get('label')):
            count += 1
    return count


def _synthesize_type_candidates(
    interactables: List[Dict[str, Any]], text: str, max_inputs: int = 2
) -> List[Dict[str, Any]]:
    """Produce generic type candidates for visible inputs in active form context.
    Excludes button-based comboboxes (which should be clicked, not typed into).
    Also excludes filter/search boxes which are not issue creation fields.
    """
    candidates: List[Dict[str, Any]] = []
    filter_search_keywords = ['filter', 'search', 'all projects', 'all issues', 'find', 'lookup', 'query']
    
    for e in interactables:
        if len(candidates) >= max_inputs:
            break
        role = (e.get('role') or '').lower()
        tag = (e.get('tag') or '').lower()
        label = (e.get('label') or e.get('placeholder') or '').lower()
        
        # Skip filter/search boxes - these are not issue creation fields
        is_filter_field = any(kw in label for kw in filter_search_keywords)
        if is_filter_field:
            continue
        
        # Textboxes and searchboxes are typeable (but skip if they're filters)
        if role in ('textbox', 'searchbox'):
            sel = e.get('selector') or ''
            if not sel:
                continue
            display_label = e.get('label') or e.get('placeholder') or 'Input'
            candidates.append({
                'action_type': 'type',
                'selector': sel,
                'label': display_label,
                'text': text,
                'score': 8.8,
                'reasoning': 'Fill visible input in active form context'
            })
        # Comboboxes: only include if they're searchable/typeable (not button-based)
        elif role == 'combobox':
            # Skip button-based comboboxes (they should be clicked, not typed)
            if tag == 'button':
                continue
            # Only include if it has a placeholder indicating it's searchable
            placeholder = (e.get('placeholder') or '').lower()
            if any(word in placeholder for word in ['search', 'type', 'enter', 'filter']):
                sel = e.get('selector') or ''
                if not sel:
                    continue
                label = e.get('label') or e.get('placeholder') or 'Input'
                candidates.append({
                    'action_type': 'type',
                    'selector': sel,
                    'label': label,
                    'text': text,
                    'score': 8.8,
                    'reasoning': 'Fill visible searchable combobox in active form context'
                })
    return candidates


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
    """Two-stage scorer: deterministic pre-ranker then compact LLM re-ranker."""
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
    top_k = int(state.get('scoring_top_k') or 15)

    # Prepare context for LLM – salience-based selection and stratified sampling
    interactables_full = state.get('interactable_elements') or []

    # Stage 0: Hard filters (drop obviously bad)
    def _hard_ok(e: Dict[str, Any]) -> bool:
        try:
            if bool(e.get('disabled', False)):
                return False
            # Size/visibility filters only if metadata available
            bbox = e.get('bbox')
            if isinstance(bbox, dict):
                try:
                    w = float(bbox.get('width') or 0)
                    h = float(bbox.get('height') or 0)
                    if w <= 1 or h <= 1:
                        return False
                except Exception:
                    pass
            op = e.get('opacity')
            if isinstance(op, (int, float)):
                if op < 0.1:
                    return False
            pe_raw = e.get('pointerEvents')
            if isinstance(pe_raw, str) and pe_raw.lower() == 'none':
                return False
            # Only consider actionable roles
            role = (e.get('role') or '').lower()
            if role not in ACTIONABLE_ROLES:
                return False
            # Must have label for most roles except some inputs
            if role not in ['textbox', 'combobox'] and not (e.get('label') or '').strip():
                return False
            return True
        except Exception:
            return False

    filtered_pool = [e for e in interactables_full if _hard_ok(e)]

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
        # Enriched visual/meta signals from observe
        try:
            if elem.get('inViewport') is True:
                base += 0.8
            bbox = elem.get('bbox') or {}
            w = float(bbox.get('width') or 0)
            h = float(bbox.get('height') or 0)
            area = w * h
            # Prefer reasonably sized tappable targets
            if area >= 400 and area <= 250000:
                base += 0.5
            opacity = elem.get('opacity')
            if isinstance(opacity, (int, float)) and opacity < 0.15:
                base -= 1.0
            pe = (elem.get('pointerEvents') or '').lower()
            if pe in ('none', 'auto'):
                # Penalize none; slight neutral for auto
                base += (-1.0 if pe == 'none' else 0.0)
        except Exception:
            pass
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

    # Bucketize and sort by salience within each bucket (on filtered pool)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for e in filtered_pool:
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

    # Diversity: MMR-like pruning by label/selector to avoid near-duplicates
    def _mmr(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen_labels: set[str] = set()
        seen_selectors: set[str] = set()
        for e in items:
            lbl = (e.get('label') or '').strip().lower()
            sel = (e.get('selector') or '').strip().lower()
            if lbl and lbl in seen_labels:
                continue
            if sel and sel in seen_selectors:
                continue
            out.append(e)
            if lbl:
                seen_labels.add(lbl)
            if sel:
                seen_selectors.add(sel)
            if len(out) >= limit:
                break
        return out

    interactables = _mmr(interactables, max_elements)

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

    # Stage 1.1: Opportunistic typing in active form contexts (generic, app-agnostic)
    active_ctx = state.get('active_context') or {}
    ctx_type = (active_ctx.get('type') or '').lower()
    is_form_ctx = (ctx_type in ('form', 'active_context'))
    # Prefer using full list for surge signal if available
    interactables_all = state.get('interactable_elements_all') or interactables_full
    textbox_count = _count_textboxes(interactables_all)
    try:
        prev_textbox_count = int(state.get('prev_textbox_count') or 0)
    except Exception:
        prev_textbox_count = 0
    textbox_surge = textbox_count > max(1, prev_textbox_count)
    state['prev_textbox_count'] = textbox_count

    should_offer_typing = (textbox_count > 0) and (is_form_ctx or textbox_surge)
    recent_actions = state.get('action_history') or []
    recent_typed = any(a.get('type') == 'type' for a in recent_actions[-3:])

    synthetic_scored: List[ScoredAction] = []
    if should_offer_typing and not recent_typed:
        # Prefer goal over instruction for better structured text (goal is decomposed and may have quotes)
        planned_text = _summarize_instruction(state.get('goal') or state.get('instruction') or '')
        if planned_text:
            try:
                synthetic_actions = _synthesize_type_candidates(interactables_full, text=planned_text, max_inputs=2)
                for a in synthetic_actions:
                    try:
                        synthetic_scored.append(
                            ScoredAction(
                                action_type=a['action_type'],
                                selector=a['selector'],
                                label=a.get('label') or 'Input',
                                score=float(a.get('score') or 8.5),
                                reasoning=a.get('reasoning') or 'Fill input',
                                text=a.get('text'),
                            )
                        )
                    except Exception:
                        continue
            except Exception:
                synthetic_scored = []

    # Short-circuit: if we have a clear typing candidate and little else, take it
    # BUT: Only if we're in the right context (form context, not filter/search pages)
    if synthetic_scored:
        try:
            top_syn = max(synthetic_scored, key=lambda a: a.score or 0.0)
            
            # Validate context: don't short-circuit if we're typing into wrong fields
            # Generic validation - no task-specific assumptions
            current_url = (state.get('current_url') or '').lower()
            action_label = (top_syn.label or '').lower()
            
            # Skip if typing into filter/search boxes (generic pattern - not form fields)
            filter_search_keywords = ['filter', 'search', 'all ', 'find', 'lookup', 'query']
            is_filter_field = any(kw in action_label for kw in filter_search_keywords)
            
            # Skip if URL suggests we're on a list/view/browse page (generic pattern)
            # These pages typically have filters, not form inputs for creation
            is_list_view = any(pattern in current_url for pattern in ['/list', '/all', '/browse', '/view/', '/items'])
            
            # Only short-circuit if:
            # 1. We're NOT on a list/view page (generic check)
            # 2. The field is NOT a filter/search box (generic check)
            # 3. We have an active form context (from active_context detection, which is already generic)
            should_short_circuit = (
                not is_list_view and 
                not is_filter_field and
                is_form_ctx  # Use the generic form context detection from above
            )
            
            if should_short_circuit:
                # If pre-ranked selection is empty or clearly weaker than typing, prefer typing now
                rest_best = 0.0
                try:
                    rest_best = max([0.0] + [float(_salience(e)) for e in interactables])
                except Exception:
                    rest_best = 0.0
                if (not interactables) or ((top_syn.score or 0.0) >= rest_best + 2.0):
                    if logger:
                        logger.log(f"Short-circuit: selecting synthetic type action on '{top_syn.label}' (context validated)", "INFO")
                    adjusted = [top_syn]
                    return {
                        'scored_actions': adjusted,
                        'next_action': None,
                        'last_scoring_fingerprint': current_fp,
                        'last_scored_step': step,
                    }
            elif logger:
                logger.log(f"Skipping short-circuit: field '{top_syn.label}' appears to be a filter/search or not in form context", "DEBUG")
        except Exception:
            pass

    # Stage 1.5: Build compact top-K for LLM re-ranker
    # Compose candidates with very short keys
    def _candidate_of(e: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'r': (e.get('role') or '')[:16],
            'l': (e.get('label') or '')[:60],
            's': e.get('selector') or '',
            'd': bool(e.get('disabled', False)),
        }

    # Pre-score with salience and take top of global list
    global_sorted = sorted(interactables, key=_salience, reverse=True)

    # Guard against instruction-derived hallucinated selectors: drop elems whose
    # label/selector largely mirrors the full instruction text
    instruction_text = (state.get('instruction') or state.get('goal') or '')
    instruction_l = instruction_text.lower().strip()
    def _looks_instruction_derived(e: Dict[str, Any]) -> bool:
        try:
            lbl = (e.get('label') or '').lower()
            sel = (e.get('selector') or '').lower()
            # If selector embeds a very long name segment from instruction, reject
            if instruction_l and ('role=' in sel) and ('[name="' in sel):
                name_part = sel.split('[name="')[-1].split('"]')[0]
                name_l = name_part.lower()
                # Consider suspicious if substantial overlap with instruction
                overlap = sum(1 for t in instruction_l.split() if len(t) >= 4 and t in name_l)
                if overlap >= 6 or len(name_l) > 80:
                    return True
            # Extremely long labels mirroring instruction are suspicious
            if instruction_l and len(lbl) > 80:
                overlap_lbl = sum(1 for t in instruction_l.split() if len(t) >= 4 and t in lbl)
                if overlap_lbl >= 6:
                    return True
        except Exception:
            return False
        return False

    filtered_for_shortlist = [e for e in global_sorted if not _looks_instruction_derived(e)]

    # Non-starvation quotas: always reserve input slots in shortlist
    inputs_pool = [e for e in filtered_for_shortlist if (e.get('role') or '').lower() in ('textbox', 'combobox')]
    submits_pool = [e for e in filtered_for_shortlist if (e.get('role') or '').lower() in ('button','link') and any(t in (e.get('label') or '').lower() for t in ['create','submit','save','send','confirm','done','finish','post'])]

    # Compute form readiness early using full observation
    try:
        form_ready = False
        interactables_all = state.get('interactable_elements_all') or interactables_full
        if any((e.get('role') or '').lower() in ('textbox','combobox') for e in interactables_all):
            form_ready = True
    except Exception:
        form_ready = False
    form_progress = int(state.get('form_progress') or 0)

    # Exclude disabled submits and premature submits when no form progress yet
    effective_submits_pool: List[Dict[str, Any]] = []
    for e in submits_pool:
        try:
            if bool(e.get('disabled', False)):
                continue
            if form_ready and form_progress <= 0:
                # Skip submits entirely until some in-form action occurs
                continue
            effective_submits_pool.append(e)
        except Exception:
            continue

    # Build shortlist: reserve inputs, then allowed submits, then fill with remaining
    reserved_inputs = inputs_pool[:max(5, min(8, top_k//2))]
    reserved_submits = effective_submits_pool[:max(1, min(2, top_k//6))]

    remainder_candidates: List[Dict[str, Any]] = []
    seen = set()
    def _mark(e: Dict[str, Any]):
        key = (e.get('selector') or '') + '|' + (e.get('role') or '')
        seen.add(key)
    for e in reserved_inputs + reserved_submits:
        _mark(e)
    for e in filtered_for_shortlist:
        key = (e.get('selector') or '') + '|' + (e.get('role') or '')
        if key in seen:
            continue
        remainder_candidates.append(e)

    shortlist_raw = (reserved_inputs + reserved_submits + remainder_candidates)
    shortlist = _mmr(shortlist_raw, top_k * 2)[:top_k]
    compact_candidates = [{ 'i': i, **_candidate_of(e) } for i, e in enumerate(shortlist)]

    if logger:
        try:
            logger.log(f"Shortlist size: {len(shortlist)} (from {len(interactables)} pre-ranked)", "DEBUG")
            logger.log(f"Compact candidates sample: {json.dumps(compact_candidates[:3])}", "DEBUG")
        except Exception:
            pass

    # Build compact prompt (short keys, minimal context)
    recent_text = chr(10).join(history_summary) if history_summary else "None"
    subtask_line = (current_sub_task['description'] if current_sub_task else 'None')
    
    # Best practice: Include LLM-formatted DOM if available (for better context)
    llm_dom_section = ""
    llm_dom = state.get('llm_dom')
    if llm_dom:
        # Truncate if too long (keep first 2000 chars for token efficiency)
        dom_preview = llm_dom[:2000] + ("..." if len(llm_dom) > 2000 else "")
        llm_dom_section = f"\n# INTERACTIVE ELEMENTS (indexed)\nInteractive elements are shown as [index]<tag>text</tag>. Only elements with [index] can be interacted with:\n{dom_preview}\n"
    
    # Include error feedback if present (short-term memory)
    error_section = ""
    short_term_error = state.get('short_term_error_memory')
    if short_term_error:
        error_section = f"\n# ERROR FEEDBACK (from last action)\n{short_term_error}\n"
    
    prompt = (
        "GOAL: " + (state.get('goal', '')[:160]) + "\n" +
        "URL: " + (state.get('current_url', '')[:140]) + "\n" +
        error_section +
        ("HINTS:\n" + dynamic_hints + "\n" if dynamic_hints else "") +
        ("SUBTASK: " + subtask_line + "\n" if sub_tasks else "") +
        llm_dom_section +
        "RECENT:\n" + recent_text + "\n" +
        "CANDIDATES (short, keys: i=index, r=role, l=label, s=selector, d=disabled):\n" + json.dumps(compact_candidates) + "\n" +
        "Pick best 'i' and provide 1-2 sentence reason. Return JSON: {\"i\": <index>, \"reason\": \"...\"}"
    )

    system_message = "Select the best next UI action index from compact candidates to advance the goal. Return only valid JSON with keys i and reason."
    
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

    if logger:
        try:
            logger.log(f"Re-ranker raw content: {content[:240]}", "DEBUG")
        except Exception:
            pass

    # Parse LLM output as a single choice; map back to candidates
    try:
        choice = json.loads(content)
    except Exception:
        choice = {}
    idx_chosen = choice.get('i')
    if isinstance(idx_chosen, int) and 0 <= idx_chosen < len(shortlist):
        chosen_elem = shortlist[idx_chosen]
        # Fabricate a ScoredAction with a high score baseline; reason captured
        reason = str(choice.get('reason') or '').strip()
        # Heuristic: decide action_type based on role
        role = (chosen_elem.get('role') or '').lower()
        tag = (chosen_elem.get('tag') or '').lower()
        inferred_type = 'click'
        
        # Textboxes are always type actions
        if role == 'textbox':
            inferred_type = 'type'
        # Comboboxes: distinguish between button-based (click) and input-based (type)
        elif role == 'combobox':
            # If it's a button tag, it's a dropdown button (click)
            # If it has a placeholder indicating searchability, it might be typeable
            # But most comboboxes in modern apps are button-based dropdowns
            if tag == 'button':
                inferred_type = 'click'  # Button-based combobox = click to open dropdown
            elif chosen_elem.get('placeholder') and any(word in (chosen_elem.get('placeholder') or '').lower() for word in ['search', 'type', 'enter', 'filter']):
                inferred_type = 'type'  # Searchable combobox = type
            else:
                # Default: button-based combobox (most common case)
                inferred_type = 'click'
        
        # Attach text for type actions using the same summarizer logic as synthetic path
        planned_text_llm = None
        try:
            if inferred_type == 'type':
                # Prefer goal over instruction for better structured text (goal is decomposed and may have quotes)
                planned_text_llm = _summarize_instruction(state.get('goal') or state.get('instruction') or '')
        except Exception:
            planned_text_llm = None
        parsed_actions = [
            ScoredAction(
                action_type=inferred_type,
                selector=str(chosen_elem.get('selector') or ''),
                label=str(chosen_elem.get('label') or ''),
                score=9.0,
                reasoning=reason or 'Chosen by compact re-ranker',
                text=planned_text_llm,
            )
        ]
    else:
        parsed_actions = []

    # Fallback: if no action chosen, synthesize a small set from shortlist
    if not parsed_actions:
        if logger:
            logger.log("Re-ranker returned no valid choice; synthesizing fallback actions from shortlist", "WARNING")
        synthesized: List[ScoredAction] = []
        for e in shortlist[:5]:
            try:
                role = (e.get('role') or '').lower()
                tag = (e.get('tag') or '').lower()
                # Use same logic as main path: textbox = type, combobox depends on tag
                if role == 'textbox':
                    inferred_type = 'type'
                elif role == 'combobox':
                    if tag == 'button':
                        inferred_type = 'click'  # Button-based combobox
                    elif e.get('placeholder') and any(word in (e.get('placeholder') or '').lower() for word in ['search', 'type', 'enter', 'filter']):
                        inferred_type = 'type'  # Searchable combobox
                    else:
                        inferred_type = 'click'  # Default: button-based
                else:
                    inferred_type = 'click'
                synthesized.append(
                    ScoredAction(
                        action_type=inferred_type,
                        selector=str(e.get('selector') or ''),
                        label=str(e.get('label') or ''),
                        score=float(8.0),
                        reasoning='Synthesized from shortlist (fallback)',
                        text=None,
                    )
                )
            except Exception:
                continue
        parsed_actions = synthesized

    # parsed_actions already constructed from the compact re-ranker choice above
    
    # Post-process: Field prioritization - boost unfilled required fields from goal
    # Extract required fields from goal and check which ones are already filled
    try:
        goal_text = (state.get('goal') or state.get('instruction') or '').lower()
        action_history = state.get('action_history') or []
        
        # Identify required fields from goal patterns
        required_fields = {}
        field_patterns = {
            'project': ['project', 'team', 'workspace'],
            'assignee': ['assign', 'assignee', 'owner', 'to user', 'to @'],
            'status': ['status', 'state', 'stage'],
            'priority': ['priority', 'urgency', 'importance'],
        }
        
        for field_name, keywords in field_patterns.items():
            if any(kw in goal_text for kw in keywords):
                required_fields[field_name] = keywords
        
        # Check which fields have been filled (from action_history)
        filled_fields = set()
        for hist_action in action_history:
            if hist_action.get('type') == 'type':
                hist_label = (hist_action.get('label') or '').lower()
                for field_name, keywords in required_fields.items():
                    if any(kw in hist_label for kw in keywords):
                        filled_fields.add(field_name)
        
        # Boost actions that match unfilled required fields
        if required_fields:
            for action in parsed_actions:
                if action.action_type == 'type':
                    action_label = (action.label or '').lower()
                    for field_name, keywords in required_fields.items():
                        if field_name not in filled_fields:
                            # Check if this action matches an unfilled required field
                            if any(kw in action_label for kw in keywords):
                                # Boost score for unfilled required fields
                                if action.score < 9.5:
                                    action.score = min(9.5, action.score + 1.5)
                                    action.reasoning = f"[REQUIRED FIELD BOOST] {action.reasoning} This field ({field_name}) is required by the goal and hasn't been filled yet."
                                    if logger:
                                        logger.log(f"Boosted {action.label} for unfilled required field: {field_name}", "DEBUG")
    except Exception as e:
        if logger:
            logger.log(f"Field prioritization failed: {e}", "DEBUG")
    
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

    # Post-process: Temporarily demote submit/confirm until in-form progress occurs
    try:
        form_ready = bool(is_form_ctx or textbox_surge)
    except Exception:
        form_ready = False
    form_progress = int(state.get('form_progress') or 0)
    if form_ready and form_progress <= 0:
        submit_terms = ['create', 'submit', 'save', 'confirm', 'done', 'post']
        for action in parsed_actions:
            try:
                if action.action_type != 'click':
                    continue
                lbl = (action.label or '').lower()
                if any(t in lbl for t in submit_terms):
                    # Cap submits to avoid outranking inputs before any form interaction
                    if action.score > 6.0:
                        action.score = 6.0
                        action.reasoning = f"[FORM READINESS GATING] {action.reasoning} Submit temporarily demoted until at least one in-form action occurs."
            except Exception:
                continue

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

    # Best practice: Limit actions per step (browser-use pattern)
    max_actions = int(state.get('max_actions_per_step') or 1)
    if len(adjusted) > max_actions:
        if logger:
            logger.log(f"Limiting actions from {len(adjusted)} to {max_actions} per step", "DEBUG")
        adjusted = adjusted[:max_actions]
    
    return {
        'scored_actions': adjusted,
        'next_action': None,
        'last_scoring_fingerprint': current_fp,
        'last_scored_step': step,
    }


