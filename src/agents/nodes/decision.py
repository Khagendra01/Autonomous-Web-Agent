from typing import Any, Dict, List, Optional
import json

from ..state import AgentState, ScoredAction
from ..utils.logger import get_logger
from ..utils.json_parser import extract_json_payload
from .common import client


def _serialize_candidates(base_list: List[ScoredAction], max_candidates: int) -> List[Dict[str, Any]]:
    return [
        {
            'i': i,
            'action_type': a.action_type,
            'label': a.label,
            'selector': a.selector,
            'score': a.score,
            'text': a.text,
            'reasoning': a.reasoning,
        }
        for i, a in enumerate(base_list[:max_candidates])
    ]


def _choose_fallback(base_list: List[ScoredAction]) -> Optional[ScoredAction]:
    if not base_list:
        return None
    # Highest score, tiebreak by label then selector for determinism
    return sorted(
        base_list,
        key=lambda a: (-float(a.score or 0.0), str(a.label or ''), str(a.selector or '')),
    )[0]


def _build_dynamic_decision_context(state: AgentState, candidates: List[Dict[str, Any]]) -> str:
    """Build dynamic context hints for decision-making (Option 6: dynamic prompting)."""
    hints = []
    action_history = state.get('action_history') or []
    errors = state.get('errors') or []
    step_count = state.get('step_count', 0)
    scored_actions = state.get('scored_actions') or []
    interactables = state.get('interactable_elements', [])
    
    # Context: Error resolution priority
    if errors:
        error_summary = ', '.join(str(e)[:50] for e in errors[:3])
        # Check if any candidates are error-resolving
        has_error_fixers = any(
            'fix' in (c.get('label') or '').lower() or
            'correct' in (c.get('label') or '').lower() or
            'resolve' in (c.get('label') or '').lower() or
            c.get('score', 0) >= 8
            for c in candidates
        )
        if has_error_fixers:
            hints.append(f"⚠️ CRITICAL: Validation errors detected: {error_summary}. Prioritize error-resolving actions (high-scored candidates). Avoid actions blocked by validation errors.")
    
    # Context: Combobox validation workflow (decision-specific)
    if action_history:
        last_action = action_history[-1]
        if last_action.get('type') == 'type':
            typed_text = last_action.get('text', '').strip()
            last_label = last_action.get('label', '')
            
    # Context: Disabled action avoidance
    disabled_submit_buttons = [
        elem.get('label', '') for elem in interactables
        if (elem.get('role') == 'button' or elem.get('role') == 'link') and
        elem.get('disabled', False) and
        any(term in (elem.get('label') or '').lower() for term in 
            ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish'])
    ]
    if disabled_submit_buttons and any(c.get('score', 0) > 2 for c in candidates):
        hints.append(
            f"⚠️ DISABLED SUBMIT BUTTON: Submit/Send button ({', '.join(disabled_submit_buttons)}) is disabled. "
            f"DO NOT select disabled actions. Look for the enabling action (e.g., selecting dropdown option, "
            f"filling required fields) that will enable the submit button. Choose a non-disabled action with a score > 2."
        )
    
    # Context: Goal completion readiness
    if scored_actions:
        top_scores = [a.score for a in scored_actions[:3] if hasattr(a, 'score')]
        if top_scores and all(s >= 8.0 for s in top_scores):
            hints.append("✅ HIGH CONFIDENCE: Multiple high-scoring candidates (≥8.0) detected. These likely represent goal-critical actions.")
    
    if step_count > 10:
        hints.append("⚠️ MANY STEPS TAKEN: Task has been ongoing. If goal is not clear, re-evaluate strategy. Consider whether submission/completion actions should be prioritized.")
    
    return '\n'.join(hints) if hints else ""


def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Choose the next action from scored candidates using LLM with robust fallbacks.

    App-agnostic policy; avoids app-specific heuristics and examples.
    """
    logger = get_logger()
    step = state.get('step_count', 0)
    if logger:
        logger.log("Selecting next action with autonomous policy", "INFO")

    if logger:
        logger.log_section(f"DECIDE - Step {step}")

    scored = state.get('scored_actions') or []
    if not scored:
        if logger:
            logger.log("No scored actions available", "WARNING")
        return { 'next_action': state.get('next_action') }

    # Configurable parameters with safe defaults
    model_name = state.get('llm_model') or "gpt-4.1"
    max_candidates = int(state.get('decision_max_candidates') or 15)

    # Filter out actions already tried on this URL to reduce loops
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    filtered_scored: List[ScoredAction] = [
        a for a in scored if f"{a.action_type}|{a.selector}" not in tried_here
    ]
    
    # Filter out actions with score < 5 to prevent choosing low-quality actions
    filtered_scored = [a for a in filtered_scored if (a.score or 0) >= 5.0]
    
    base_list = filtered_scored if filtered_scored else scored

    # Generic gating: block commit/submit actions until requirements are satisfied
    # Commit-like labels: submit, save, create, send, confirm, done, finish, post
    reqs = state.get('requirements') or {}
    unmet_requirements = [k for k, v in reqs.items() if v is False]
    if unmet_requirements:
        if logger:
            logger.log_dict("Prerequisite Gating", {
                'unmet_requirements': unmet_requirements,
                'note': 'Commit-like actions will be suppressed until requirements are met.'
            })
        commit_terms = ['submit', 'save', 'create', 'send', 'confirm', 'done', 'finish', 'post']
        gated: List[ScoredAction] = []
        blocked: List[ScoredAction] = []
        for a in base_list:
            label_lower = (a.label or '').lower()
            is_commit = any(term in label_lower for term in commit_terms)
            if is_commit:
                blocked.append(a)
            else:
                gated.append(a)
        if gated:
            base_list = gated
        # If everything was blocked, keep base_list unchanged to avoid deadlock

    # Avoid immediate repetition of the exact same action (type|selector) as last executed
    action_history = state.get('action_history') or []
    if action_history:
        last = action_history[-1]
        last_key = f"{last.get('type','')}|{last.get('selector','')}"
        non_repeating: List[ScoredAction] = [a for a in base_list if f"{a.action_type}|{a.selector}" != last_key]
        if non_repeating:
            base_list = non_repeating

    if not base_list:
        if logger:
            logger.log("No candidates available after filtering", "WARNING")
        return { 'next_action': state.get('next_action') }

    candidates = _serialize_candidates(base_list, max_candidates)

    recent = (state.get('action_history') or [])[-5:]
    errors = state.get('errors') or []
    goal = state.get('goal') or ''
    instruction = state.get('instruction') or ''
    current_url_str = state.get('current_url') or ''
    step_count = state.get('step_count', 0)

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_decision_context(state, candidates)

    # Build structured prompt with clear sections (Option 2)
    prompt = f"""# ROLE & OBJECTIVE
You are an autonomous web agent's decision module. Your task is to select the single best next UI action from scored candidates to advance toward the user's goal.

# CONTEXT
Goal: {goal}
Instruction: {instruction}
Current URL: {current_url_str}
Step Count: {step_count}

Errors/Validation Issues:
{json.dumps(errors) if errors else "None"}

Recent Actions (last 5):
{json.dumps(recent) if recent else "None"}

{"## DYNAMIC CONTEXT HINTS" + chr(10) + dynamic_hints + chr(10) if dynamic_hints else ""}
# CANDIDATE ACTIONS
Select one candidate by its index 'i':
{json.dumps(candidates)}

# DECISION PRINCIPLES

## Score Guidance (Important):
- When scores differ significantly (≥3 points), prefer higher-scored candidates unless there's a BLOCKING reason (disabled, validation error)
- When scores are close (within 2 points), use reasoning about goal alignment, context, and feasibility to choose
- Scores represent LLM assessment - consider them but apply judgment for edge cases
- If high-scored action is blocked/disabled, find the enabling action instead

## Goal Advancement (CRITICAL)
- Prefer actions that clearly advance the stated goal
- Consider how each candidate's score and reasoning relate to the goal
- If multiple high-scoring options exist, choose the one with clearest goal alignment

## Error Resolution (CRITICAL)
- If validation or error signals exist, prioritize resolving them (see Dynamic Context Hints)
- Avoid actions blocked by validation errors
- Error resolution typically takes precedence over goal progression

## Disabled Actions (CRITICAL)
- NEVER select disabled Submit/Send buttons - they cannot be clicked
- If submit button is disabled, find the enabling action (e.g., selecting dropdown option, filling required field)
- Look for validation steps that enable the submit button (see Dynamic Context Hints for combobox validation workflow)
- Only select disabled actions if they are the ONLY available option and there's no enabling action

## Efficiency & Avoidance (IMPORTANT)
- Avoid repeating ineffective recent actions
- Prioritize goal-directed actions over exploration

## Rationale Quality (IMPORTANT)
- Be honest about candidate quality in your rationale
- Explain why the chosen action is best given current context
- If all candidates are weak, acknowledge this and choose the least risky option

## Text Override Guidance
- For type actions, you may override the suggested text if you have a better value
- Use textOverride only when you're confident the override improves goal progress
- Leave textOverride as null if the candidate's original text is appropriate

# OUTPUT FORMAT
Return ONLY valid JSON:
{{
  "i": <candidate index (0-based)>,
  "rationale": "2-3 sentence explanation of why this action is best",
  "textOverride": "optional text for type actions, or null"
}}"""

    system_message = """You are an autonomous web agent's decision module. Your role is to select the optimal next UI action from scored candidates. You must make principled decisions based on goal alignment, error resolution priorities, and efficiency. Return only valid JSON following the specified format."""
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ]
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        if logger:
            logger.log(f"Decision LLM call failed: {e}", "ERROR")
        fallback = _choose_fallback(base_list)
        return { 'next_action': fallback }

    decision = extract_json_payload(content) or {}
    try:
        idx = int(decision.get('i', 0))
    except Exception:
        idx = 0
    rationale = (decision.get('rationale') or '').strip()
    text_override = decision.get('textOverride')

    if 0 <= idx < len(candidates) and idx < len(base_list):
        chosen = base_list[idx]
        if chosen.action_type == 'type' and text_override is not None:
            chosen = ScoredAction(
                action_type=chosen.action_type,
                selector=chosen.selector,
                label=chosen.label,
                score=chosen.score,
                reasoning=rationale or chosen.reasoning,
                text=str(text_override),
            )
        else:
            chosen = ScoredAction(
                action_type=chosen.action_type,
                selector=chosen.selector,
                label=chosen.label,
                score=chosen.score,
                reasoning=rationale or chosen.reasoning,
                text=chosen.text,
            )
        if logger:
            logger.log(f"Chosen: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}'", "INFO")
            if rationale:
                logger.log(f"Rationale: {rationale}", "INFO")
        
        if logger:
            logger.log_dict("Chosen Action", {
                'action_type': chosen.action_type,
                'label': chosen.label,
                'selector': chosen.selector,
                'score': chosen.score,
                'reasoning': chosen.reasoning,
                'text': chosen.text if chosen.action_type == 'type' else None,
                'rationale': rationale
            })
        
        return { 'next_action': chosen }

    if logger:
        logger.log(f"Invalid index {idx}; using fallback", "WARNING")
    fallback = _choose_fallback(base_list)
    return { 'next_action': fallback }

