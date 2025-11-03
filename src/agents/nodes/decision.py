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
    max_candidates = int(state.get('decision_max_candidates') or 12)

    # Filter out actions already tried on this URL to reduce loops
    # Best practice: Resolve indices to selectors for consistent comparison
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    
    # Resolve indices to selectors for accurate filtering
    index_map = state.get('llm_index_to_selector') or {}
    
    def _get_comparison_selector(action: ScoredAction) -> str:
        """Get selector for comparison, resolving index if needed."""
        sel = action.selector
        try:
            if sel.isdigit():
                idx = int(sel)
                return index_map.get(idx, sel)  # Return resolved selector or original
        except (ValueError, AttributeError):
            pass
        return sel
    
    def _get_action_key(action: ScoredAction) -> str:
        """Get action key for tried_actions_by_url comparison, including text for type actions."""
        resolved_sel = _get_comparison_selector(action)
        if action.action_type == 'type' and action.text:
            return f"{action.action_type}|{resolved_sel}|{action.text[:50]}"
        return f"{action.action_type}|{resolved_sel}"
    
    def _is_action_tried(action: ScoredAction) -> bool:
        """Check if action (or same field for type actions) has been tried.
        For type actions, checks both base key (field) and text-specific key."""
        base_key = f"{action.action_type}|{_get_comparison_selector(action)}"
        if base_key in tried_here:
            return True
        # For type actions, also check text-specific key
        if action.action_type == 'type' and action.text:
            text_key = f"{action.action_type}|{_get_comparison_selector(action)}|{action.text[:50]}"
            if text_key in tried_here:
                return True
        return False
    
    filtered_scored: List[ScoredAction] = [
        a for a in scored if not _is_action_tried(a)
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

    # Avoid immediate repetition AND prevent typing into any field already typed into
    # Best practice: action_history now stores resolved selectors, so direct comparison works
    action_history = state.get('action_history') or []
    if action_history:
        last = action_history[-1]
        last_selector = last.get('selector', '')  # Already resolved from execute.py
        last_key = f"{last.get('type','')}|{last_selector}"
        
        # For type actions: prevent typing into ANY field that's been typed into before (not just last one)
        # This prevents going back to previously filled fields
        # Track by both selector AND label for robustness (selectors can change, labels are more stable)
        # Also track count to detect loops (same field typed 2+ times)
        typed_fields_selectors = set()
        typed_fields_labels = set()
        typed_fields_count = {}  # Track how many times each field was typed into
        typed_fields_text = {}  # Track text typed into each field to detect duplicate text loops
        
        for hist_action in action_history:
            if hist_action.get('type') == 'type':
                hist_selector = hist_action.get('selector', '')
                hist_label = (hist_action.get('label') or '').strip().lower()
                hist_text = (hist_action.get('text') or '').strip().lower()
                
                if hist_selector:
                    typed_fields_selectors.add(hist_selector)
                    typed_fields_count[hist_selector] = typed_fields_count.get(hist_selector, 0) + 1
                    if hist_text:
                        typed_fields_text[hist_selector] = typed_fields_text.get(hist_selector, set())
                        typed_fields_text[hist_selector].add(hist_text[:50])  # Store first 50 chars
                
                if hist_label:
                    typed_fields_labels.add(hist_label)
                    typed_fields_count[f"label:{hist_label}"] = typed_fields_count.get(f"label:{hist_label}", 0) + 1
        
        non_repeating: List[ScoredAction] = []
        for a in base_list:
            candidate_key = f"{a.action_type}|{_get_comparison_selector(a)}"
            # Skip if it's the exact last action
            if candidate_key == last_key:
                continue
            # Skip if it's a type action on a field we've already typed into
            # Check both selector AND label for robustness
            if a.action_type == 'type':
                resolved_sel = _get_comparison_selector(a)
                action_label = (a.label or '').strip().lower()
                action_text = (a.text or '').strip().lower()
                
                # Skip if field was already typed into (by selector or label)
                if resolved_sel in typed_fields_selectors:
                    # Additional check: if same text was typed before, definitely skip (loop detection)
                    if action_text and resolved_sel in typed_fields_text:
                        if action_text[:50] in typed_fields_text[resolved_sel]:
                            if logger:
                                logger.log(f"Skipping type action on '{a.label}': same text already typed (loop prevention)", "DEBUG")
                            continue
                    # Skip if typed into 2+ times (likely a loop)
                    if typed_fields_count.get(resolved_sel, 0) >= 2:
                        if logger:
                            logger.log(f"Skipping type action on '{a.label}': field typed into {typed_fields_count.get(resolved_sel, 0)} times (loop prevention)", "DEBUG")
                        continue
                    continue
                
                if action_label and action_label in typed_fields_labels:
                    # Skip if typed into 2+ times by label
                    if typed_fields_count.get(f"label:{action_label}", 0) >= 2:
                        if logger:
                            logger.log(f"Skipping type action on '{a.label}': field typed into {typed_fields_count.get(f'label:{action_label}', 0)} times by label (loop prevention)", "DEBUG")
                        continue
                    continue
            non_repeating.append(a)
        
        if non_repeating:
            base_list = non_repeating

    if not base_list:
        if logger:
            logger.log("No candidates available after filtering", "WARNING")
        # Best practice: Retry on empty actions - clear error memory and return empty
        return {
            'next_action': state.get('next_action'),
            'short_term_error_memory': 'No valid actions available after filtering. Page may have changed.',
        }

    # Short-circuit when trivial
    if len(base_list) == 1:
        only = base_list[0]
        if logger:
            logger.log("Only one candidate available; selecting without LLM", "INFO")
        return { 'next_action': only }
    try:
        sorted_by_score = sorted(base_list, key=lambda a: float(a.score or 0.0), reverse=True)
        if len(sorted_by_score) >= 2 and (float(sorted_by_score[0].score or 0.0) - float(sorted_by_score[1].score or 0.0) >= 2.5):
            if logger:
                logger.log("Top candidate has clear lead (>=2.5); selecting without LLM", "INFO")
            return { 'next_action': sorted_by_score[0] }
    except Exception:
        pass

    # Compact candidates with short keys (for prompt)
    compact_candidates = [
        {
            'i': i,
            'r': (a.action_type or '')[:12],
            'l': (a.label or '')[:60],
            's': a.selector or '',
            'd': False,
            'k': float(a.score or 0.0),
        }
        for i, a in enumerate(base_list[:max_candidates])
    ]
    # Verbose candidates for dynamic hints (keeps expected keys like 'label', 'score')
    verbose_candidates = _serialize_candidates(base_list, max_candidates)

    recent = (state.get('action_history') or [])[-5:]
    errors = state.get('errors') or []
    goal = state.get('goal') or ''
    instruction = state.get('instruction') or ''
    current_url_str = state.get('current_url') or ''
    step_count = state.get('step_count', 0)

    # Build dynamic context hints with verbose schema
    dynamic_hints = _build_dynamic_decision_context(state, verbose_candidates)

    # Build compact prompt with legend for keys
    compact_recent = json.dumps(recent[-3:]) if recent else "None"
    compact_errors = ", ".join(errors[:2]) if errors else "None"
    
    # Best practice: Include LLM-formatted DOM if available
    llm_dom_section = ""
    llm_dom = state.get('llm_dom')
    if llm_dom:
        dom_preview = llm_dom[:1500] + ("..." if len(llm_dom) > 1500 else "")
        llm_dom_section = f"\n# INTERACTIVE ELEMENTS\n[index]<tag>text</tag> format - only indexed elements are interactive:\n{dom_preview}\n"
    
    # Include error feedback if present
    error_section = ""
    short_term_error = state.get('short_term_error_memory')
    if short_term_error:
        error_section = f"\n# ERROR FEEDBACK\n{short_term_error}\n"
    
    prompt = (
        "GOAL: " + (goal[:160]) + "\n" +
        "URL: " + (current_url_str[:140]) + "\n" +
        error_section +
        ("HINTS:\n" + dynamic_hints + "\n" if dynamic_hints else "") +
        llm_dom_section +
        "ERRORS: " + compact_errors + "\n" +
        "RECENT: " + compact_recent + "\n" +
        "CANDIDATES (keys: i=index, r=action_type, l=label, s=selector, d=disabled, k=score): " + json.dumps(compact_candidates) + "\n" +
        "Pick best index 'i'. Return JSON {\"i\": <index>, \"reason\": \"...\"}."
    )

    system_message = "Select the best next UI action index from compact candidates to advance the goal. Return only JSON with keys i and reason."
    
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
    rationale = (decision.get('reason') or decision.get('rationale') or '').strip()

    if 0 <= idx < len(base_list):
        chosen = base_list[idx]
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

