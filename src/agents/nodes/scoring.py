from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
from ..utils.dom import summarize_accessibility_tree
from ..utils.logger import get_logger
from .common import client


def _action_key_from_scored(action: ScoredAction) -> str:
    # Key prioritizes selector + type which best identifies a unique UI action
    # Include index if available for browser-use format
    if action.index is not None:
        return f"{action.action_type}|index:{action.index}|{action.selector}"
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


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions are most likely to advance the goal (app-agnostic)."""
    goal = state.get('goal', '')
    print(f"\n[SCORE] Analyzing actions for goal: {goal}")

    # Configurable parameters
    model_name = state.get('llm_model') or "gpt-4.1"
    max_elements = int(state.get('scoring_max_elements') or 80)

    # Use browser-use format if available, fallback to legacy format
    dom_state_text = state.get('dom_state_llm_text')
    selector_map = state.get('selector_map', {})
    use_browser_use_format = dom_state_text is not None and selector_map

    # Build action history summary
    history_summary = []
    for i, action in enumerate((state.get('action_history') or [])[-5:]):  # Last 5 actions
        history_summary.append(f"{i+1}. {action.get('type', '')} on '{action.get('label', 'N/A')}'")

    if use_browser_use_format:
        # Use browser-use format
        prompt = f"""You are assisting an autonomous web agent. Score interactive elements by how likely they are to help achieve the goal.

Context:
- Goal: {state.get('goal', '')}
- Instruction: {state.get('instruction', '')}
- Current URL: {state.get('current_url', '')}
- Recent Actions:\n{chr(10).join(history_summary) if history_summary else "None"}

Interactive Elements (browser-use format):
Each interactive element is shown as [index]<tag>text</tag> with attributes.
Only elements with [index] are clickable. Use the index number to reference them.

{dom_state_text[:8000]}

Task: Return a JSON array of recommended actions with scores from 0-10 indicating usefulness toward the goal.

Scoring scale:
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Possibly useful or indirectly related
- 0-3 = Unlikely to help or wrong direction

Generic principles:
1) Disabled elements are not actionable → score 0-2; prefer enabling steps first.
2) Prefer elements whose labels/roles semantically match goal terms; consider aria-label, placeholder, title, and text.
3) If the goal requires data entry, prioritize relevant input fields; if submission is clearly required and ready, prioritize submission controls.
4) If no strong candidates exist, include low-risk exploration (e.g., scroll/open menu) to reveal options.
5) Avoid repeating recently ineffective actions.
6) If there are validation errors, prioritize actions that resolve them.

IMPORTANT: Use the index number from [index] in the format above. For example, if you see [123]<button>Submit</button>, use index 123.

Return ONLY a JSON array of objects like:
[
  {{"index": 123, "label": "…", "action_type": "click|type|scroll", "text": "optional", "score": 0-10, "reasoning": "…"}}
]
"""
    else:
        # Fallback to legacy format
        dom_summary = summarize_accessibility_tree(state.get('dom_snapshot') or {})
        interactables_full = state.get('interactable_elements') or []
        interactables = interactables_full[:max_elements]

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

    logger = get_logger()
    logger.llm(f"Scoring prompt sent to LLM", {
        "model": model_name,
        "prompt_length": len(prompt),
        "prompt_preview": prompt[:1000] + "..." if len(prompt) > 1000 else prompt
    })
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Score UI actions for goal completion. Return only valid JSON array."},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
        
        logger.llm(f"LLM scoring response received", {
            "response_length": len(content),
            "response_preview": content[:500] + "..." if len(content) > 500 else content
        })
    except Exception as e:
        print(f"  Scoring LLM call failed: {e}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Scoring LLM call failed: {e}",
        }

    scored_actions_raw = _extract_json_array(content) or []

    logger.debug(f"Parsing {len(scored_actions_raw)} scored actions from LLM")
    
    parsed_actions: List[ScoredAction] = []
    for a in scored_actions_raw:
        try:
            action_type = str(a.get('action_type'))
            label = str(a.get('label', ''))
            score = float(a.get('score', 0))
            reasoning = str(a.get('reasoning', ''))
            text = a.get('text')
            
            # Handle browser-use format (index-based) vs legacy (selector-based)
            index = a.get('index')
            selector = a.get('selector', '')
            
            if use_browser_use_format and index is not None:
                # Browser-use format: resolve selector from index
                try:
                    index_int = int(index)
                    if index_int in selector_map:
                        selector = selector_map[index_int].get('selector', '')
                        parsed_actions.append(
                            ScoredAction(
                                action_type=action_type,
                                selector=selector,
                                index=index_int,
                                label=label,
                                score=score,
                                reasoning=reasoning,
                                text=text,
                            )
                        )
                except (ValueError, TypeError):
                    # Invalid index, skip this action
                    continue
            elif selector:
                # Legacy format: use selector directly
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
    
    # Log all scored actions
    logger.llm(f"Parsed scored actions", {
        "total": len(adjusted),
        "actions": [
            {
                "index": action.index,
                "action_type": action.action_type,
                "label": action.label,
                "score": action.score,
                "selector": action.selector,
                "backend_node_id": selector_map.get(action.index, {}).get('backend_node_id') if action.index and use_browser_use_format else None
            }
            for action in adjusted[:10]  # Log top 10
        ]
    })
    
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


