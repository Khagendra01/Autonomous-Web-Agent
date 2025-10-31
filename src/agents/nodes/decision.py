from typing import Any, Dict, List
import json

from ..state import AgentState, ScoredAction
from .common import client


def decide_action_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to choose the next action from scored candidates - PURE LLM DECISION, NO HEURISTICS."""
    print(f"\n[DECIDE] Selecting next action using pure LLM policy (no heuristics)")

    scored = state.get('scored_actions') or []
    if not scored:
        return { 'next_action': state.get('next_action') }

    # Filter out actions already tried on this URL to avoid loops
    current_url = state.get('current_url') or ''
    tried_map = state.get('tried_actions_by_url') or {}
    tried_here: List[str] = tried_map.get(current_url, [])
    filtered_scored: List[ScoredAction] = [a for a in scored if f"{a.action_type}|{a.selector}" not in tried_here]
    if filtered_scored:
        if len(filtered_scored) != len(scored):
            print("  Skipping previously tried action(s) on this page; choosing next best candidate")
        base_list = filtered_scored
    else:
        # If we've exhausted options, fall back to full list to avoid stalling
        base_list = scored

    # Ensure we have candidates
    if not base_list:
        print(f"  ⚠️  No candidates available")
        return { 'next_action': state.get('next_action') }
    
    # Prepare candidate list for LLM decision
    candidates = [
        {
            'i': i,
            'action_type': a.action_type,
            'label': a.label,
            'selector': a.selector,
            'score': a.score,
            'text': a.text,
            'reasoning': a.reasoning,
        }
        for i, a in enumerate(base_list[:15]) # Show more candidates for better LLM choice
    ]

    recent = state['action_history'][-5:]
    errors = state.get('errors') or []

    prompt = f"""You are an autonomous web agent decision policy. Choose the next UI action from candidates.

Goal (normalized): {state['goal']}
Full instruction (verbatim): {state.get('instruction', '')}
Current URL: {state['current_url']}
Errors/Validation: {json.dumps(errors)}
Recent actions (last 5): {json.dumps(recent)}

Candidates (choose one by index 'i'):
{json.dumps(candidates, indent=2)}

DECISION STRATEGY:
You must balance two competing needs:

1. **ENTITY GROUNDING FIRST (CRITICAL)**:
   - If the goal includes a specific entity name (e.g., a page titled "Daily Journal"), choose actions that open/navigate to that exact entity BEFORE attempting any destructive or context-dependent action (like Delete, Edit, More...). Prefer exact-text matches; if not visible, use Search to find it.

2. **EXPLOITATION** (using high-scored actions):
   - When you see a high-scored action (≥7.0) that directly advances the goal, strongly prefer it
   - High scores mean the action is semantically aligned with the goal
   - Exploit clear opportunities to make progress

3. **EXPLORATION** (discovering new options):
   - When ALL candidates have low scores (<5.0), it means nothing obvious advances the goal
   - In this case, PREFER scroll/exploratory actions to discover new UI elements
   - Clicking poor-scored actions (score < 5.0) is likely to waste steps or move in wrong direction
   - Scroll is especially valuable when: stuck in same place, no high-quality options visible, or repeated low scores
   
4. **ERROR RECOVERY**:
   - If validation errors exist, prioritize actions that address them (e.g., fill required fields)
   - Errors indicate the last action was incomplete - look for what's missing

5. **AVOID LOOPS**:
   - Check recent action history - don't repeat ineffective patterns
   - If you've tried high-scored actions without progress, switch to exploration
   - Sometimes a strategic scroll or menu opening unlocks the next step

6. **QUALITY AWARENESS**:
   - Be honest about candidate quality in your rationale
   - If max score is <5.0, acknowledge options are weak
   - Don't pretend a score-3.0 action is good - use it only if exploration exhausted

STRATEGIC EXAMPLES:
- Goal "delete page titled Daily Journal": If a link or result named "Daily Journal" is present, click it first. Only after the page is opened should "Delete" or "More" be chosen.
- Top score 9.5 "Create project button" → Click it (high exploitation value)
- Top score 4.2 "Random link", scroll available → Scroll (explore for better options)
- Top score 7.5 but already clicked 2 times → Try scroll or 2nd-best option
- Validation error "Name required" + score 8.5 "Name textbox" → Type name (error recovery)

Return ONLY a JSON object:
{{
  "i": <candidate index>,
  "rationale": "why this action is the best next step (mention if exploiting high score vs exploring)",
  "textOverride": "optional text for type actions or null"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an autonomous web navigation agent. Make strategic decisions to reach the goal. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        decision = json.loads(content)
        idx = int(decision.get('i', 0))
        rationale = decision.get('rationale') or ''
        text_override = decision.get('textOverride')

        if 0 <= idx < len(candidates) and idx < len(base_list):
            chosen = base_list[idx]
            
            # Apply optional text override if LLM provided it
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

            print(f"  ✓ Chosen: [{chosen.score:.1f}] {chosen.action_type} '{chosen.label}'")
            print(f"  Rationale: {rationale}")
            return { 'next_action': chosen }

        # Fallback to first candidate
        print(f"  ⚠️  Invalid index {idx}, falling back to first candidate")
        return { 'next_action': base_list[0] }

    except Exception as e:
        print(f"  ⚠️  Failed to parse decision: {e}")
        # Fallback to highest scored action
        return { 'next_action': base_list[0] if base_list else None }


