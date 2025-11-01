from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
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


def _get_role_priority_by_task(role: str, goal: str) -> float:
    """Determine role priority based on the task/goal context.
    
    Returns priority score for a role based on what the task requires.
    Higher score = more relevant for this task.
    """
    goal_lower = goal.lower()
    role_lower = role.lower()
    
    # Default base scores (neutral baseline)
    base_scores = {
        'button': 1.0,
        'textbox': 1.0,
        'combobox': 1.0,
        'link': 1.0,
        'menuitem': 1.0,
        'option': 1.0,
        'checkbox': 0.8,
        'radio': 0.8,
    }
    
    base = base_scores.get(role_lower, 0.5)
    
    # Task-specific boosts based on goal content
    # Input-related tasks
    if any(word in goal_lower for word in ['fill', 'enter', 'type', 'input', 'write', 'add text', 'provide']):
        if role_lower in ['textbox', 'combobox']:
            return base + 1.5  # Boost inputs for data entry tasks
        if role_lower == 'button' and 'submit' not in goal_lower:
            return base + 0.3  # Buttons less important unless submitting
    
    # Click/navigation tasks
    if any(word in goal_lower for word in ['click', 'open', 'navigate', 'go to', 'visit', 'follow link', 'goto']):
        if role_lower in ['link', 'button']:
            return base + 1.5  # Boost clickable elements
        if role_lower == 'menuitem':
            return base + 1.2
    
    # Form submission tasks
    if any(word in goal_lower for word in ['submit', 'save', 'send', 'post', 'publish', 'create']):
        if role_lower == 'button':
            return base + 1.8  # Strong boost for buttons on submit tasks
        if role_lower in ['textbox', 'combobox']:
            return base + 0.8  # Inputs important but secondary
    
    # Selection/choice tasks
    if any(word in goal_lower for word in ['select', 'choose', 'pick', 'option']):
        if role_lower in ['option', 'menuitem', 'checkbox', 'radio', 'combobox']:
            return base + 1.5  # Boost selectable elements
        if role_lower == 'button':
            return base + 0.5  # Buttons less relevant
    
    # Search/filter tasks
    if any(word in goal_lower for word in ['search', 'find', 'filter', 'look for']):
        if role_lower == 'textbox':
            return base + 1.8  # Search boxes very important
        if role_lower == 'button' and 'search' in goal_lower:
            return base + 1.0  # Search button important
        if role_lower == 'link':
            return base + 0.3  # Links less relevant
    
    # Menu/dropdown tasks
    if any(word in goal_lower for word in ['menu', 'dropdown', 'select from', 'choose from']):
        if role_lower in ['menuitem', 'option', 'combobox']:
            return base + 1.8
        if role_lower == 'button':
            return base + 0.5
    
    # Default: return base score if no specific match
    return base


def _prioritize_elements(
    interactables: List[Dict[str, Any]], 
    goal: str, 
    max_elements: int,
    errors: List[str]
) -> List[Dict[str, Any]]:
    """Intelligently select and prioritize elements before sending to LLM.
    
    Strategies:
    1. Filter disabled elements (but keep some for context)
    2. Keyword matching against goal to boost relevance
    3. Context-aware role priority (adapts to task type - e.g., textbox for "fill form", link for "click link")
    4. Ensure diversity (different roles, different positions)
    5. Stratified sampling to get elements from different parts of list
    """
    if len(interactables) <= max_elements:
        return interactables
    
    goal_lower = goal.lower()
    goal_keywords = set(re.findall(r'\b\w+\b', goal_lower))
    
    # Extract keywords from errors too (for error resolution priority)
    error_keywords = set()
    for error in errors:
        error_keywords.update(re.findall(r'\b\w+\b', error.lower()))
    
    # Score each element for relevance
    scored_elements = []
    for i, elem in enumerate(interactables):
        label = (elem.get('label') or '').lower()
        role = (elem.get('role') or '').lower()
        placeholder = (elem.get('placeholder') or '').lower()
        elem_id = (elem.get('id') or '').lower()
        classes = ' '.join(elem.get('classes', [])).lower()
        
        # 1. Position bonus (earlier elements slightly preferred, but not dominant)
        position_bonus = 1.0 - (i / len(interactables)) * 0.1  # 0.9 to 1.0
        
        # 2. Keyword matching (strong signal)
        text_to_search = f"{label} {placeholder} {elem_id} {classes}"
        matches = sum(1 for keyword in goal_keywords if len(keyword) > 2 and keyword in text_to_search)
        keyword_score = min(matches * 2.0, 10.0)
        
        # 3. Error-related elements (if errors exist)
        if errors and any(keyword in text_to_search for keyword in error_keywords if len(keyword) > 2):
            keyword_score += 3.0
        
        # 4. Role priority (context-aware based on task)
        role_score = _get_role_priority_by_task(role, goal)
        
        # 5. Disabled penalty (but don't exclude completely - LLM should see them)
        disabled_penalty = -1.0 if elem.get('disabled', False) else 0.0
        
        # 6. Action words in label (verbs and action terms that indicate important buttons/controls)
        action_words = {
            # Creation/Submission
            'create', 'save', 'submit', 'add', 'new', 'post', 'publish', 'send', 'upload',
            # Modification
            'edit', 'update', 'modify', 'change', 'alter',
            # Deletion
            'delete', 'remove', 'clear', 'cancel',
            # Confirmation/Acceptance
            'confirm', 'ok', 'apply', 'accept', 'agree', 'approve', 'proceed',
            # Navigation/Progress
            'next', 'continue', 'finish', 'done', 'complete', 'submit',
            # Actions
            'share', 'invite', 'export', 'import', 'download', 'sync', 'refresh',
            'search', 'find', 'filter', 'sort', 'reset',
            # Forms
            'login', 'signin', 'signup', 'register', 'join', 'subscribe',
            'pay', 'purchase', 'buy', 'checkout', 'order',
            # Social
            'like', 'follow', 'comment', 'reply', 'message', 'chat',
            # Other common actions
            'activate', 'enable', 'disable', 'start', 'stop', 'pause', 'resume',
            'open', 'close', 'expand', 'collapse', 'show', 'hide', 'view',
            'select', 'choose', 'pick', 'set', 'configure', 'setup', 'install',
        }
        # Check if any action word appears in label (case-insensitive)
        label_lower = label.lower()
        action_bonus = 1.5 if any(word in label_lower for word in action_words) else 0.0
        
        total_score = (
            keyword_score * 3.0 +      # Keyword matches are most important
            role_score +
            action_bonus +
            disabled_penalty
        ) * position_bonus
        
        scored_elements.append((total_score, i, elem))
    
    # Sort by score (highest first)
    scored_elements.sort(key=lambda x: x[0], reverse=True)
    
    # Stratified selection: mix high-scored + diverse roles + position diversity
    selected_indices = set()
    selected = []
    
    # Phase 1: Take top-scored elements (50% of budget)
    top_count = max_elements // 2
    for score, idx, elem in scored_elements[:top_count]:
        if idx not in selected_indices:
            selected.append(elem)
            selected_indices.add(idx)
    
    # Phase 2: Ensure role diversity (fill remaining slots with diverse roles)
    role_counts = {}
    for score, idx, elem in scored_elements:
        if idx in selected_indices:
            continue
        role = elem.get('role', '')
        role_counts[role] = role_counts.get(role, 0)
        if role_counts[role] < 5:  # Max 5 per role for diversity
            selected.append(elem)
            selected_indices.add(idx)
            role_counts[role] += 1
            if len(selected) >= max_elements:
                break
    
    # Phase 3: Fill remaining slots with elements from different positions (stratified sampling)
    if len(selected) < max_elements:
        remaining = max_elements - len(selected)
        step = max(1, len(interactables) // remaining)
        for i in range(0, len(interactables), step):
            if i not in selected_indices and len(selected) < max_elements:
                selected.append(interactables[i])
                selected_indices.add(i)
    
    # Final fallback: if still need more, take highest scored remaining
    if len(selected) < max_elements:
        for score, idx, elem in scored_elements:
            if idx not in selected_indices:
                selected.append(elem)
                selected_indices.add(idx)
                if len(selected) >= max_elements:
                    break
    
    return selected[:max_elements]


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions are most likely to advance the goal (app-agnostic)."""
    goal = state.get('goal', '')
    print(f"\n[SCORE] Analyzing actions for goal: {goal}")

    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4o"

    # Prepare context for LLM
    interactables_full = state.get('interactable_elements') or []
    
    # Calculate max_elements as 15% of total interactables (rounded to int) if not specified in state
    total_count = len(interactables_full)
    default_max = int(round(total_count * 0.15))
    max_elements = int(state.get('scoring_max_elements') or default_max)
    errors = state.get('errors') or []
    
    # Use intelligent prioritization instead of just taking first N elements
    interactables = _prioritize_elements(
        interactables_full, 
        goal, 
        max_elements,
        errors
    )
    
    print(f"  Selected {len(interactables)} elements from {len(interactables_full)} total (prioritized by relevance)")

    # Build action history summary
    history_summary = []
    for i, action in enumerate((state.get('action_history') or [])[-5:]):  # Last 5 actions
        history_summary.append(f"{i+1}. {action.get('type', '')} on '{action.get('label', 'N/A')}'")

    prompt = f"""You are assisting an autonomous web agent. Score interactive elements by how likely they are to help achieve the goal.

Context:
- Goal: {state.get('goal', '')}
- Instruction: {state.get('instruction', '')}
- Current URL: {state.get('current_url', '')}
- Recent Actions:\n{chr(10).join(history_summary) if history_summary else "None"}

Available Interactive Elements (truncated):
{json.dumps(interactables, indent=2)}

Task: Return a JSON array of recommended actions with scores from 0-10 indicating usefulness toward the goal.

Scoring scale:
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Possibly useful or indirectly related
- 0-3 = Unlikely to help or wrong direction

Generic principles:
1) Disabled elements (disabled=true) are not actionable → score 0-2; prefer enabling steps first.
2) Prefer elements whose labels/roles semantically match goal terms; consider aria-label, placeholder, title, and text.
3) If the goal requires data entry, prioritize relevant input fields; if submission is clearly required and ready, prioritize submission controls.
4) If no strong candidates exist, include low-risk exploration (e.g., scroll/open menu) to reveal options.
5) Avoid repeating recently ineffective actions.
6) If there are validation errors, prioritize actions that resolve them.

Selector guidance:
- Use a single, specific selector (no commas). Prefer role-based selectors, e.g., role=button[name="…"], role=textbox[name="…"].

Return ONLY a JSON array of objects like:
[
  {{"selector": "role=button[name=\"…\"]", "label": "…", "action_type": "click|type|scroll", "text": "optional", "score": 0-10, "reasoning": "…"}}
]
"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Score UI actions for goal completion. Return only valid JSON array."},
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

    # Choose action based on retry logic: try first action twice before moving to second
    chosen_action: Optional[ScoredAction] = None
    if adjusted:
        first_action = adjusted[0]
        first_action_key = _action_key_from_scored(first_action)
        
        # Count how many times the first action has been tried recently
        action_history = state.get('action_history') or []
        retry_count = 0
        current_url = state.get('current_url') or ''
        
        # Count occurrences of the first action key in recent history
        # We check the last 10 actions to see if we've already tried this action
        for action_record in reversed(action_history[-10:]):
            action_key = f"{action_record.get('type', '')}|{action_record.get('selector', '')}"
            if action_key == first_action_key:
                retry_count += 1
        
        # If we've tried the first action 2 or more times, move to the second action
        if retry_count >= 2 and len(adjusted) > 1:
            chosen_action = adjusted[1]
            print(f"  [RETRY LOGIC] First action tried {retry_count} times, choosing second action")
            print(f"  Chosen: [{chosen_action.score:.1f}] {chosen_action.action_type} '{chosen_action.label}'")
        else:
            chosen_action = first_action
            if retry_count > 0:
                print(f"  [RETRY LOGIC] First action tried {retry_count} time(s), retrying (max 2 attempts)")
            print(f"  Chosen: [{chosen_action.score:.1f}] {chosen_action.action_type} '{chosen_action.label}'")
    else:
        print("  No actions available to choose")

    return {
        'scored_actions': adjusted,
        'next_action': chosen_action,
    }

