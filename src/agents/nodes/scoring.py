from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
from ..utils.dom import summarize_accessibility_tree
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


def _build_dynamic_context_hints(state: AgentState, interactables: List[Dict[str, Any]]) -> str:
    """Build dynamic context hints based on current state (Option 6: dynamic prompting)."""
    hints = []
    action_history = state.get('action_history') or []
    errors = state.get('errors') or []
    step_count = state.get('step_count', 0)
    
    # Context: Error resolution priority
    if errors:
        error_summary = ', '.join(str(e)[:50] for e in errors[:3])
        hints.append(f"⚠️ CRITICAL: Validation errors detected: {error_summary}. Prioritize actions that resolve these errors (score 8-10 for error-fixing actions, 0-3 for actions blocked by errors).")
    
    # Context: Early stage exploration
    if step_count < 3:
        hints.append("🔍 EARLY STAGE: Task just started. Include exploration actions (scroll, open menus) to discover available options. Score exploration actions 4-6 even if not directly goal-related.")
    
    # Context: Combobox redundancy detection
    if action_history:
        last_action = action_history[-1]
        if last_action.get('type') == 'type':
            typed_text = last_action.get('text', '').strip().lower()
            if typed_text:
                # Check for dropdown options matching typed text
                has_matching_options = any(
                    elem.get('role') == 'option' and 
                    (typed_text in (elem.get('label') or '').lower() or 
                     (elem.get('label') or '').lower() in typed_text)
                    for elem in interactables
                )
                if has_matching_options:
                    hints.append(f"⚠️ REDUNDANCY WARNING: Recently typed '{typed_text}' into combobox field. Dropdown options matching this text are likely redundant - the field already contains this value. Score such options 0-3; prefer moving to next field or submitting instead.")
    
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
    goal = state.get('goal', '')
    print(f"\n[SCORE] Analyzing actions for goal: {goal}")

    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4o"
    max_elements = int(state.get('scoring_max_elements') or 80)

    # Prepare context for LLM
    dom_summary = summarize_accessibility_tree(state.get('dom_snapshot') or {})
    interactables_full = state.get('interactable_elements') or []
    interactables = interactables_full[:max_elements]

    # Build action history summary
    history_summary = []
    action_history = state.get('action_history') or []
    for i, action in enumerate(action_history[-5:]):  # Last 5 actions
        text_part = f" with text '{action.get('text')}'" if action.get('type') == 'type' and action.get('text') else ""
        history_summary.append(f"{i+1}. {action.get('type', '')} on '{action.get('label', 'N/A')}'{text_part}")

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_context_hints(state, interactables)

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

    return {
        'scored_actions': adjusted,
        'next_action': None,
    }


