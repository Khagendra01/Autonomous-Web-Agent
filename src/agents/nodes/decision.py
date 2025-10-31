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


def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Choose the next action from scored candidates using LLM with robust fallbacks.

    App-agnostic policy; avoids app-specific heuristics and examples.
    """
    print(f"\n[DECIDE] Selecting next action with autonomous policy")

    scored = state.get('scored_actions') or []
    if not scored:
        return { 'next_action': state.get('next_action') }

    # Configurable parameters with safe defaults
    model_name = state.get('llm_model') or "gpt-5-mini"
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

    prompt = f"""You are an autonomous web agent policy. Choose the best next UI action by index.

Context:
- Goal: {goal}
- Instruction: {instruction}
- Current URL: {current_url_str}
- Errors/Validation: {json.dumps(errors)}
- Recent actions (last 5): {json.dumps(recent)}

Candidates (select one by index 'i'):
{json.dumps(candidates, indent=2)}

Decision principles (generic, app-agnostic):
1) Prefer actions that clearly advance the stated goal.
2) When high-quality options are absent, prefer low-risk exploration (e.g., scroll, open menu) to reveal better options.
3) If validation or error signals exist, prioritize resolving them.
4) Avoid repeating ineffective recent actions.
5) Be honest about candidate quality in the rationale.

Return ONLY valid JSON:
{{
  "i": <candidate index>,
  "rationale": "brief why this action is best",
  "textOverride": "optional text for type actions or null"
}}"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are an autonomous web navigation agent. Return only valid JSON."},
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

