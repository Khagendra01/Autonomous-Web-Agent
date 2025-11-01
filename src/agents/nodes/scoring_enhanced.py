"""Enhanced scoring node with better message formatting and structured output."""
from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
from ..utils.message_formatter import format_action_scoring_prompt
from .common import client


def _action_key_from_scored(action: ScoredAction) -> str:
    """Create unique key for action deduplication."""
    return f"{action.action_type}|{action.selector}"


def _extract_json_array(text: str) -> Optional[List[Any]]:
    """Extract JSON array from LLM response with robust parsing."""
    # Strip code fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()
    
    # Try direct parse
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


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Score actions using enhanced prompting and structured output.
    
    Improvements:
    1. Uses formatted prompts with better context
    2. Better error handling
    3. Improved deduplication logic
    4. More informative logging
    """
    goal = state.get('goal', '')
    instruction = state.get('instruction', '')
    print(f"\n[SCORE] Analyzing actions for goal: {goal}")

    # Get selector map (enhanced structure)
    selector_map = state.get('selector_map')
    if not selector_map:
        # Fallback to old format if selector_map not available
        from ..utils.dom_enhanced import process_interactable_elements
        raw_elements = state.get('interactable_elements', [])
        selector_map = process_interactable_elements(raw_elements)
    
    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4o"
    
    # Get context
    current_url = state.get('current_url', '')
    action_history = state.get('action_history', [])
    errors = state.get('errors', [])
    
    # Build enhanced prompt
    prompt = format_action_scoring_prompt(
        goal=goal,
        instruction=instruction,
        current_url=current_url,
        selector_map=selector_map,
        action_history=action_history,
        errors=errors,
    )
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Score UI actions for goal completion. Return only valid JSON array."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Lower temperature for more consistent scoring
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  ❌ Scoring LLM call failed: {e}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Scoring LLM call failed: {e}",
        }
    
    # Parse scored actions
    scored_actions_raw = _extract_json_array(content) or []
    
    parsed_actions: List[ScoredAction] = []
    for a in scored_actions_raw:
        try:
            action_type = str(a.get('action_type', 'click'))
            selector = str(a.get('selector', ''))
            label = str(a.get('label', ''))
            
            # Validate action type
            if action_type not in ['click', 'type', 'scroll', 'navigate']:
                continue
            
            score = float(a.get('score', 0))
            reasoning = str(a.get('reasoning', ''))
            text = a.get('text')
            
            if not selector:
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
        except (ValueError, TypeError, KeyError) as e:
            print(f"  ⚠️  Skipping invalid action: {e}")
            continue
    
    # Deduplicate by action_type|selector key, keeping highest score
    unique_by_key: Dict[str, ScoredAction] = {}
    for a in parsed_actions:
        k = _action_key_from_scored(a)
        existing = unique_by_key.get(k)
        if existing is None or a.score > existing.score:
            unique_by_key[k] = a
    
    deduped: List[ScoredAction] = list(unique_by_key.values())
    
    # Sort by score descending
    adjusted: List[ScoredAction] = sorted(
        deduped,
        key=lambda x: float(x.score or 0.0),
        reverse=True
    )
    
    # Log results
    print(f"  ✓ Scored {len(adjusted)} unique actions")
    if adjusted:
        print(f"  Top 3 candidates:")
        for i, action in enumerate(adjusted[:3], 1):
            text_suffix = f" (text: '{action.text}')" if action.text else ""
            print(f"    {i}. [{action.score:.1f}] {action.action_type} '{action.label}'{text_suffix}")
            if action.reasoning:
                print(f"       → {action.reasoning[:80]}...")
        
        # Show score groups
        if len(adjusted) > 1:
            top_score = adjusted[0].score
            same_group = [a for a in adjusted if a.score >= top_score - 1.0][:8]
            if len(same_group) > 1:
                print(f"  High-score group (±1.0 from top={top_score:.1f}):")
                for a in same_group:
                    suffix = f" → type '{a.text}'" if (a.action_type == 'type' and a.text) else ""
                    print(f"    - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix}")
    
    return {
        'scored_actions': adjusted,
        'next_action': None,
    }

