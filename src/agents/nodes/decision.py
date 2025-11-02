from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
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


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    # Remove code fences if present
    if "```" in text:
        parts = text.split("```")
        # Prefer the first fenced block content
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()

    # Try direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Fallback: find the first top-level JSON object via regex
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        return None
    return None


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
            typed_text = last_action.get('text', '').strip().lower()
            last_label = last_action.get('label', '').lower()
            
            # Check if we typed into a combobox field
            is_combobox_field = (
                'combobox' in last_label or
                'type the name' in last_label or
                'recipient' in last_label or
                'to' in last_label
            )
            
            if typed_text and is_combobox_field:
                # Check candidates for matching dropdown options
                matching_candidates = [
                    c for c in candidates
                    if c.get('action_type') == 'click' and
                    (typed_text in (c.get('label') or '').lower() or
                     (c.get('label') or '').lower() in typed_text)
                ]
                
                if matching_candidates:
                    # Check if any candidate is a disabled submit/send button
                    has_disabled_submit_candidate = any(
                        c.get('label', '').lower() in ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish']
                        and any(
                            # Try to detect if this would be disabled - we don't have direct access to disabled state
                            # but we can infer from low scores (disabled buttons often scored 0-2)
                            (scored_actions and 
                             any(a.label.lower() == c.get('label', '').lower() and a.score <= 2
                                 for a in scored_actions[:10]))
                        )
                        for c in candidates
                    )
                    
                    # Check for explicitly disabled actions
                    has_disabled_submit_element = any(
                        (elem.get('role') == 'button' or elem.get('role') == 'link') and
                        elem.get('disabled', False) and
                        any(term in (elem.get('label') or '').lower() for term in 
                            ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish'])
                        for elem in interactables
                    )
                    
                    if has_disabled_submit_element or has_disabled_submit_candidate:
                        # This is validation workflow - prioritize selecting dropdown option
                        option_labels = [c.get('label', 'N/A') for c in matching_candidates[:2]]
                        hints.append(
                            f"🔗 COMBOBOX VALIDATION: Select matching dropdown option ({', '.join(option_labels)}) "
                            f"to validate input and enable Send button. This is REQUIRED before Send will work. "
                            f"AVOID clicking disabled Send button."
                        )
                    else:
                        # No disabled submit - might be redundant
                        option_labels = [c.get('label') for c in matching_candidates[:2]]
                        hints.append(
                            f"⚠️ REDUNDANCY WARNING: Recently typed '{typed_text}' into combobox. "
                            f"Candidate dropdown options matching this text ({', '.join(option_labels)}) are likely redundant. "
                            f"AVOID selecting these; prefer moving to next field, submitting, or other productive actions."
                        )
    
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
            hints.append("✅ HIGH CONFIDENCE: Multiple high-scoring candidates (≥8.0) detected. These likely represent goal-critical actions. Prioritize these over exploration.")
    
    # Context: Exploration stage
    if step_count < 3:
        hints.append("🔍 EARLY STAGE: Task just started. If goal-directed actions are unclear, prefer low-risk exploration (scroll, open menus) to discover options.")
    elif step_count > 15:
        hints.append("⚠️ MANY STEPS TAKEN: Task has been ongoing. If goal is not clear, re-evaluate strategy. Consider whether submission/completion actions should be prioritized.")
    
    return '\n'.join(hints) if hints else ""


def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Choose the next action from scored candidates using LLM with robust fallbacks.

    App-agnostic policy; avoids app-specific heuristics and examples.
    """
    print(f"\n[DECIDE] Selecting next action with autonomous policy")

    scored = state.get('scored_actions') or []
    if not scored:
        return { 'next_action': state.get('next_action') }

    # Configurable parameters with safe defaults
    model_name = state.get('llm_model') or "gpt-4o"
    max_candidates = int(state.get('decision_max_candidates') or 15)

    # Filter out actions already tried on this URL to reduce loops
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    filtered_scored: List[ScoredAction] = [
        a for a in scored if f"{a.action_type}|{a.selector}" not in tried_here
    ]
    base_list = filtered_scored if filtered_scored else scored

    if not base_list:
        print("  No candidates available after filtering")
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
{json.dumps(errors, indent=2) if errors else "None"}

Recent Actions (last 5):
{json.dumps(recent, indent=2) if recent else "None"}

{"## DYNAMIC CONTEXT HINTS" + chr(10) + dynamic_hints + chr(10) if dynamic_hints else ""}
# CANDIDATE ACTIONS
Select one candidate by its index 'i':
{json.dumps(candidates, indent=2)}

# DECISION PRINCIPLES

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
- When high-quality goal-directed options are absent, prefer low-risk exploration (scroll, open menu)
- Balance immediate goal progress with necessary discovery

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
        print(f"  Decision LLM call failed: {e}")
        fallback = _choose_fallback(base_list)
        return { 'next_action': fallback }

    decision = _extract_json_payload(content) or {}
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
        print(f"  Chosen: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}'")
        if rationale:
            print(f"  Rationale: {rationale}")
        return { 'next_action': chosen }

    print(f"  Invalid index {idx}; using fallback")
    fallback = _choose_fallback(base_list)
    return { 'next_action': fallback }

