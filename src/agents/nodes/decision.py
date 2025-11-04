from typing import Any, Dict, List, Optional
import json
import re

from ..state import AgentState, ScoredAction
from .common import client
from ..utils.logger import get_logger


def _extract_index_from_response(text: str) -> Optional[int]:
    """Extract a single integer index from LLM response."""
    # Try direct JSON parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            idx = obj.get('i') or obj.get('index')
            if idx is not None:
                return int(idx)
        if isinstance(obj, int):
            return obj
    except Exception:
        pass
    
    # Try code fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:].strip()
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    idx = obj.get('i') or obj.get('index')
                    if idx is not None:
                        return int(idx)
            except Exception:
                pass
    
    # Try regex to find a number
    match = re.search(r'\b(\d+)\b', text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            pass
    
    return None


def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Choose the next action from scored candidates using a small LLM call with minimal context.
    
    Uses past actions and goal to make a contextual decision from the top-scored candidates.
    """
    print(f"\n[DECIDE] Selecting best action with contextual constraints")

    scored = state.get('scored_actions') or []
    if not scored:
        print("  No scored actions available")
        return { 'next_action': state.get('next_action') }

    # Filter out actions already tried - check BOTH current URL and recent actions globally
    # This prevents loops where agent keeps clicking same button even after URL changes
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    
    # ALSO check recent action history globally (last 10 actions) to avoid retrying same action
    # even if URL changed (e.g., clicking "Projects" on homepage, then clicking it again on projects page)
    recent_actions = (state.get('action_history') or [])[-10:]
    tried_globally = set()
    for act in recent_actions:
        action_key = f"{act.get('type', '')}|{act.get('selector', '')}"
        if action_key:
            tried_globally.add(action_key)
    
    # Combine: tried on this URL OR tried recently globally
    all_tried = set(tried_here) | tried_globally
    
    # Filter out ALL tried actions
    available_actions = [
        a for a in scored 
        if f"{a.action_type}|{a.selector}" not in all_tried
    ]
    
    # Log what we filtered out
    filtered_count = len(scored) - len(available_actions)
    if filtered_count > 0:
        print(f"  Filtered out {filtered_count} already-tried actions ({len(set(tried_here) - tried_globally)} from current URL, {len(tried_globally - set(tried_here))} from recent history)")

    if not available_actions:
        print("  No candidates available after filtering")
        return { 'next_action': state.get('next_action') }

    # Limit to top 8 candidates for LLM decision
    candidates_for_llm = available_actions[:8]
    
    # Get recent action history (last 5 actions) for prompt context
    recent_actions_for_prompt = (state.get('action_history') or [])[-5:]
    goal = state.get('goal') or ''
    
    # Build simple actions summary
    actions_summary = []
    for i, act in enumerate(recent_actions_for_prompt):
        action_str = f"{act.get('type', 'unknown')} on '{act.get('label', 'N/A')}'"
        if act.get('type') == 'type' and act.get('text'):
            action_str += f" (typed: '{act['text'][:30]}')"
        actions_summary.append(f"{i+1}. {action_str}")
    
    candidates_list = []
    for i, action in enumerate(candidates_for_llm):
        candidate_str = f"{i}. [{action.score:.1f}] {action.action_type} '{action.label}'"
        if action.reasoning:
            candidate_str += f" - {action.reasoning[:100]}"
        candidates_list.append(candidate_str)
    
    prompt = f"""Choose the best action to achieve the goal. Be logical and rational.

Goal: {goal}

What I already tried (DON'T REPEAT THESE):
{chr(10).join(actions_summary) if actions_summary else "Nothing yet"}

Available actions (select by number):
{chr(10).join(candidates_list)}

Think logically:
- What is the next concrete step to achieve the goal?
- If looking for a project, find project NAMES/CARDS (not navigation buttons like "Projects" or "All projects")
- If looking for an issue, find "Create issue" or issue-related buttons
- Don't repeat actions already tried - they're already filtered out

Return ONLY the candidate number (0-{len(candidates_for_llm)-1}) as JSON: {{"i": <number>}}
"""

    logger = get_logger()
    logger.llm(f"Decision prompt (minimal context)", {
        "prompt_length": len(prompt),
        "candidates_count": len(candidates_for_llm),
        "recent_actions_count": len(recent_actions_for_prompt)
    })
    
    # Small LLM call with minimal context
    chosen = None
    try:
        response = client.chat.completions.create(
            model=state.get('llm_model') or "gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a web navigation agent. Choose actions logically to achieve the goal. Don't repeat actions already tried. Return only JSON with candidate index."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Lower temperature for more deterministic choices
            max_tokens=50  # Small response - just need a number
        )
        content = (response.choices[0].message.content or "").strip()
        
        logger.llm(f"LLM decision response", {
            "response": content,
            "response_length": len(content)
        })
        
        idx = _extract_index_from_response(content)
        if idx is not None and 0 <= idx < len(candidates_for_llm):
            chosen = candidates_for_llm[idx]
            print(f"  LLM selected: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}' (candidate #{idx})")
        else:
            print(f"  ⚠️  LLM returned invalid index {idx}, using highest score fallback")
            chosen = candidates_for_llm[0]
    except Exception as e:
        print(f"  ⚠️  LLM call failed: {e}, using highest score fallback")
        logger.warning(f"Decision LLM call failed", {"error": str(e)})
        chosen = candidates_for_llm[0]
    
    logger.info(f"Selected action", {
        "action_type": chosen.action_type,
        "label": chosen.label,
        "score": chosen.score,
        "index": chosen.index,
        "selector": chosen.selector,
        "reasoning": chosen.reasoning,
        "was_tried": f"{chosen.action_type}|{chosen.selector}" in all_tried
    })
    
    print(f"  Final choice: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}'")
    if chosen.reasoning:
        print(f"  Reasoning: {chosen.reasoning}")
    if f"{chosen.action_type}|{chosen.selector}" in all_tried:
        print(f"  ⚠️  WARNING: This action was tried before! This shouldn't happen after filtering.")

    return { 'next_action': chosen }

