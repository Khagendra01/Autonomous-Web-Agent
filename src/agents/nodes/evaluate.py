from typing import Any, Dict, Optional, List
import json
import re

from ..state import AgentState
from .common import client


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        return None
    return None


def _extract_required_values(goal: str, instruction: str) -> List[str]:
    """Extract specific values that must be entered/created from the goal/instruction.
    
    Looks for patterns like:
    - "create a project called X"
    - "create X"
    - "enter X"
    - "type X"
    - "named X"
    """
    text = f"{goal} {instruction}".lower()
    values = []
    
    # Patterns that indicate a specific name/value must be entered
    patterns = [
        # Pattern 1: "called X" or "named X" - capture word(s) until stop words
        (r'(?:called|named|titled|titled as)\s+["\']?([^"\'\s]+(?:\s+[^"\'\s]+)*?)["\']?(?:\s+(?:in|on|for|with|using|via)\s+|$)', 1),
        # Pattern 2: "create project called X" - similar to pattern 1
        (r'(?:create|make|add|enter|type|write|fill)\s+(?:a|an|the)?\s+(?:new\s+)?(?:project|item|task|issue|note|card|board|list|team|workspace|page|document|file|folder)\s+(?:called|named|titled|titled as)\s+["\']?([^"\'\s]+(?:\s+[^"\'\s]+)*?)["\']?(?:\s+(?:in|on|for|with|using|via)\s+|$)', 1),
        # Pattern 3: Quoted strings directly - these are most reliable
        (r'["\']([^"\']+)["\']', 1),
        # Pattern 4: "enter name X" or "type value X"
        (r'(?:enter|type|write|fill in)\s+(?:the\s+)?(?:name|value|text)\s+["\']([^"\']+)["\']', 1),
    ]
    
    for pattern, group_idx in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if not matches:
            continue
        for match in matches:
            # Handle tuple results (multiple groups)
            if isinstance(match, tuple):
                match = match[group_idx - 1] if len(match) > group_idx - 1 else match[0]
            if match and len(match.strip()) > 1:
                # Stop at common preposition words
                words = match.strip().split()
                filtered_words = []
                stop_words = {'in', 'on', 'at', 'for', 'with', 'to', 'from', 'using', 'via', 'by'}
                for word in words:
                    if word.lower() in stop_words:
                        break
                    filtered_words.append(word)
                if filtered_words:
                    values.append(' '.join(filtered_words))
    
    # Also look for quoted strings as potential required values
    quoted = re.findall(r'["\']([^"\']{3,})["\']', text)
    values.extend(quoted)
    
    # Deduplicate and filter out common words
    seen = set()
    filtered = []
    common_words = {'new', 'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'with', 'create', 'make', 'add'}
    for v in values:
        v_lower = v.lower()
        if v_lower not in seen and v_lower not in common_words and len(v) >= 2:
            seen.add(v_lower)
            filtered.append(v)
    
    return filtered


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether the goal is complete using LLM with robust, app-agnostic criteria."""
    print(f"\n[CHECK GOAL] Evaluating goal completion")
    print(f"  Goal: {state.get('goal', '')}")
    print(f"  Steps taken: {state.get('step_count', 0)}")

    model_name = state.get('llm_model') or "gpt-4o"
    recent_actions = (state.get('action_history') or [])[-5:]

    # Normalize action details for evaluation
    action_details: List[Dict[str, Any]] = []
    for a in recent_actions:
        action_details.append({
            'type': a.get('type', ''),
            'label': a.get('label', ''),
            'text': a.get('text', ''),
            'score': a.get('score', 0),
            'reasoning': a.get('reasoning', ''),
        })
    
    # Pre-check: If goal requires entering/creating a specific value, verify it was typed
    goal = state.get('goal', '')
    instruction = state.get('instruction', '')
    required_values = _extract_required_values(goal, instruction)
    
    if required_values:
        print(f"  Required values to verify: {required_values}")
        # Check if any type action matches the required values
        typed_values = [a.get('text', '') for a in action_details if a.get('type') == 'type']
        found_values = []
        for req_val in required_values:
            req_lower = req_val.lower()
            for typed in typed_values:
                if typed and (req_lower in typed.lower() or typed.lower() in req_lower):
                    found_values.append(req_val)
                    break
        
        missing_values = [v for v in required_values if v not in found_values]
        if missing_values:
            print(f"  ⚠️  Warning: Required values not entered yet: {missing_values}")
            print(f"  Typed values in history: {typed_values}")

    last_action = action_details[-1] if action_details else None
    if last_action:
        text_part = f" with text '{last_action['text']}'" if last_action.get('text') else ""
        print(f"  Last action: {last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})")

    # Build verification note for the prompt
    verification_note = ""
    if required_values:
        typed_values = [a.get('text', '') for a in action_details if a.get('type') == 'type']
        missing_values = []
        for req_val in required_values:
            req_lower = req_val.lower()
            found = any(typed and (req_lower in typed.lower() or typed.lower() in req_lower) for typed in typed_values)
            if not found:
                missing_values.append(req_val)
        
        if missing_values:
            verification_note = f"\n\nCRITICAL VERIFICATION: The goal requires entering/creating these specific values: {required_values}. These values MUST appear in a 'type' action in the action history to consider completion. Currently missing from typed actions: {missing_values}. If any required values are missing, the task is NOT complete."
        else:
            verification_note = f"\n\nVERIFICATION: Required values {required_values} were found in typed actions. This is good evidence of progress."

    prompt = f"""Assess whether the user's goal has been completed based on the action history and current state.

Context:
- Goal: {state.get('goal', '')}
- Instruction: {state.get('instruction', '')}
- Current URL: {state.get('current_url', '')}
- Steps Taken: {state.get('step_count', 0)}
- Errors: {json.dumps(state.get('errors', []))}
{verification_note}
Most recent action:
{json.dumps(last_action, indent=2) if last_action else "None"}

Complete Action History (chronological):
{json.dumps(action_details, indent=2)}

Currently Available UI Elements (if any):
{json.dumps(state.get('interactable_elements', []), indent=2)}

Evaluation principles (generic, app-agnostic):
1) Favor completion when a coherent workflow of actions aligns with the goal and no errors are present.
2) If a visible submission/confirmation control remains (e.g., a generic submit/confirm control), prefer marking as incomplete.
3) CRITICAL: If the goal requires entering/creating a specific named value (e.g., "create project called X"), you MUST see a "type" action with that value in the action history. Do NOT assume completion just because the value appears in UI elements - it must have been explicitly typed.
4) Consider typed values matching goal parameters as strong evidence of progress/completion.
5) Avoid over-caution: many modern apps auto-save; absence of explicit submit does not always imply incompletion.
6) Provide a concise, evidence-based rationale referencing specific actions.

Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "short evidence-based explanation",
  "confidence": 0.0-1.0,
  "missing_steps": ["optional list of next steps if not complete"]
}}"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You evaluate whether a web task is complete. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  Evaluation LLM call failed: {e}")
        return {'goal_reached': False}

    result = _extract_json_payload(content) or {}
    goal_reached = bool(result.get('goal_reached', False))
    reasoning = (result.get('reasoning') or 'Unknown').strip()
    try:
        confidence = float(result.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    missing_steps = result.get('missing_steps', []) or []

    # Final safety check: if required values exist and weren't typed, override to incomplete
    if required_values and goal_reached:
        typed_values = [a.get('text', '') for a in action_details if a.get('type') == 'type']
        missing_values = []
        for req_val in required_values:
            req_lower = req_val.lower()
            found = any(typed and (req_lower in typed.lower() or typed.lower() in req_lower) for typed in typed_values)
            if not found:
                missing_values.append(req_val)
        
        if missing_values:
            print(f"  ⚠️  OVERRIDE: Goal marked complete by LLM, but required values not typed: {missing_values}")
            print(f"  Forcing goal_reached=False due to missing typed values")
            goal_reached = False
            reasoning = f"Required value(s) '{', '.join(missing_values)}' must be entered but were not found in action history. " + reasoning
            confidence = min(confidence, 0.3)  # Lower confidence

    print(f"  Goal reached: {goal_reached} (confidence: {confidence:.1%})")
    if reasoning:
        print(f"  Reasoning: {reasoning}")
    if missing_steps:
        try:
            print(f"  Missing steps: {', '.join(map(str, missing_steps))}")
        except Exception:
            print("  Missing steps: (unprintable)")

    return { 'goal_reached': goal_reached }


