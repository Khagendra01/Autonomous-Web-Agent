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
    
    # Get recent goal evaluation to check for specific action recommendations
    goal_reasoning = state.get('goal_evaluation_reasoning') or ''
    missing_steps = state.get('goal_missing_steps') or []
    missing_steps_text = ', '.join(str(step) for step in missing_steps) if missing_steps else 'None'
    
    # Extract button/action names mentioned in missing steps (FORCE preference)
    mentioned_actions = set()
    if missing_steps or goal_reasoning:
        all_text = ' '.join(str(step) for step in missing_steps) + ' ' + goal_reasoning.lower()
        
        # Pattern 1: "click Send", "click the Send button", "click 'Send' button", etc.
        # More flexible: handles quotes or no quotes
        matches1 = re.findall(r'(?:click|press|select|use|activate)\s+(?:and\s+)?(?:activate\s+and\s+)?(?:the\s+)?(?:"|\'|)([\w]+)(?:"|\'|)?(?:\s+button)?', all_text, re.IGNORECASE)
        for action_name in matches1:
            clean_name = action_name.strip().lower()
            if len(clean_name) > 2 and clean_name not in ['the', 'and', 'to', 'for']:  # Filter out noise
                mentioned_actions.add(clean_name)
        
        # Pattern 2: Standalone button names like "Send button", "'Send' button"
        matches2 = re.findall(r'(?:"|\'|)([\w]+)(?:"|\'|)?\s+button', all_text, re.IGNORECASE)
        for action_name in matches2:
            clean_name = action_name.strip().lower()
            if len(clean_name) > 2:
                mentioned_actions.add(clean_name)
        
        # Pattern 3: Simple button mention: "the Send button", "Send button"
        matches3 = re.findall(r'(?:the\s+)?([\w]+)\s+button', all_text, re.IGNORECASE)
        for action_name in matches3:
            clean_name = action_name.strip().lower()
            if len(clean_name) > 2 and clean_name not in ['the', 'and', 'to', 'for']:
                mentioned_actions.add(clean_name)
        
        # Debug: show what we extracted
        if mentioned_actions:
            print(f"  🔍 Goal evaluation mentions actions: {', '.join(sorted(mentioned_actions))}")
        elif missing_steps or goal_reasoning:
            # Debug output if no matches found
            print(f"  ℹ️  No action names extracted from missing steps (text: {all_text[:100]}...)")
    
    # Identify candidates that match mentioned actions from goal evaluation
    matching_candidates = []
    if mentioned_actions:
        for idx, candidate in enumerate(candidates):
            candidate_label = (candidate.get('label') or '').lower()
            # Check for exact or very close matches
            for mentioned_action in mentioned_actions:
                if len(mentioned_action) > 2:
                    # Exact match or contained match
                    if mentioned_action == candidate_label or \
                       (mentioned_action in candidate_label and len(mentioned_action) > 3) or \
                       (candidate_label in mentioned_action and len(candidate_label) > 3):
                        matching_candidates.append((idx, candidate.get('label'), mentioned_action))
                        print(f"    ✅ Match found: '{candidate.get('label')}' matches '{mentioned_action}' from goal evaluation")

    prompt = f"""You are an autonomous web agent policy. Choose the best next UI action by index.

Context:
- Goal: {goal}
- Instruction: {instruction}
- Current URL: {current_url_str}
- Errors/Validation: {json.dumps(errors)}
- Recent actions (last 5): {json.dumps(recent)}
- Recent goal evaluation reasoning: {goal_reasoning}
- Missing steps identified: {missing_steps_text}

Candidates (select one by index 'i'):
{json.dumps(candidates, indent=2)}

{f"**CRITICAL MATCHES FOUND**: The following candidates match actions mentioned in missing steps: {', '.join(f'index {idx} (\"{label}\" matches \"{action}\")' for idx, label, action in matching_candidates)}" if matching_candidates else ""}

Decision principles (generic, app-agnostic):
1) **MANDATORY PRIORITY**: The "missing steps" explicitly state what action needs to be taken next. You MUST select the candidate that matches the action mentioned in missing steps. {"If matches are listed above, you MUST select one of those matching candidates." if matching_candidates else ""} For example, if missing steps say "Click the Send button", you MUST select the candidate with label "Send" or containing "Send", regardless of scores. This is non-negotiable - the goal evaluation has already determined what needs to happen.
2) Only if no candidate matches the missing steps should you consider other factors.
3) Prefer actions that clearly advance the stated goal.
4) When high-quality options are absent, prefer low-risk exploration (e.g., scroll, open menu) to reveal better options.
5) If validation or error signals exist, prioritize resolving them.
6) Avoid repeating ineffective recent actions.
7) Be honest about candidate quality in the rationale.

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

