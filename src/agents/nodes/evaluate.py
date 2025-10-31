from typing import Any, Dict, Optional, List
import json
import re

from ..state import AgentState
from .common import client
from ..utils.logger import get_logger


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
    # Determine which goal we're checking (current_goal if multiple goals exist)
    multiple_goals = state.get('multiple_goal')
    current_goal = state.get('current_goal')
    active_goal = current_goal if (multiple_goals and current_goal) else state.get('goal', '')
    
    logger = get_logger()
    
    logger.info(f"\n[CHECK GOAL] Evaluating goal completion")
    if multiple_goals and current_goal:
        goal_index = multiple_goals.index(current_goal) + 1 if current_goal in multiple_goals else 1
        logger.info(f"  Goal {goal_index}/{len(multiple_goals)}: {active_goal}")
        if len(multiple_goals) > goal_index:
            logger.info(f"  Remaining goals: {', '.join(multiple_goals[goal_index:])}")
    else:
        logger.info(f"  Goal: {active_goal}")
    logger.info(f"  Steps taken: {state.get('step_count', 0)}")

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
    # Use active_goal (current_goal if multiple goals exist, otherwise goal)
    instruction = state.get('instruction', '')
    required_values = _extract_required_values(active_goal, instruction)
    
    if required_values:
        logger.info(f"  Required values to verify: {required_values}")
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
            logger.warning(f"  ⚠️  Warning: Required values not entered yet: {missing_values}")
            logger.info(f"  Typed values in history: {typed_values}")

    last_action = action_details[-1] if action_details else None
    if last_action:
        text_part = f" with text '{last_action['text']}'" if last_action.get('text') else ""
        logger.info(f"  Last action: {last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})")

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

    # Build goal context for prompt
    goal_context = active_goal
    if multiple_goals and current_goal:
        goal_index = multiple_goals.index(current_goal) + 1 if current_goal in multiple_goals else 1
        goal_context = f"[Goal {goal_index}/{len(multiple_goals)}] {active_goal}"
        if len(multiple_goals) > goal_index:
            remaining = ', '.join(multiple_goals[goal_index:])
            goal_context += f"\nNote: This is part of a sequence. After completing this goal, remaining goals are: {remaining}"
    
    # Always ask for prioritized roles when goal is not reached (will be conditionally included)
    prioritized_roles_instruction = """
7) IMPORTANT: If the goal is NOT reached, analyze what types of UI elements (roles) are most critical to interact with next. For example:
   - If missing input data: prioritize 'textbox' or 'combobox'
   - If need to navigate: prioritize 'link' or 'button'
   - If need to select option: prioritize 'option', 'menuitem', or 'combobox'
   - If need to submit: prioritize 'button'
   Return a list of role names (lowercase) in "prioritized_roles" that should be boosted in the next iteration."""
    
    prompt = f"""Assess whether the user's goal has been completed based on the action history and current state.

Context:
- Goal: {goal_context}
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
6) Provide a concise, evidence-based rationale referencing specific actions.{prioritized_roles_instruction}

Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "short evidence-based explanation",
  "confidence": 0.0-1.0,
  "missing_steps": ["optional list of next steps if not complete"],
  "prioritized_roles": ["role1", "role2", ...]  // Only if goal_reached=false: list of UI roles (e.g., "textbox", "button", "link") to prioritize in next iteration
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
        logger.error(f"  Evaluation LLM call failed: {e}")
        return {'goal_reached': False}

    result = _extract_json_payload(content) or {}
    goal_reached = bool(result.get('goal_reached', False))
    reasoning = (result.get('reasoning') or 'Unknown').strip()
    try:
        confidence = float(result.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    missing_steps = result.get('missing_steps', []) or []
    
    # Extract prioritized roles if goal is not reached
    prioritized_roles = []
    if not goal_reached:
        prioritized_roles_raw = result.get('prioritized_roles', [])
        if isinstance(prioritized_roles_raw, list):
            # Normalize role names to lowercase and filter valid roles
            valid_roles = {'button', 'textbox', 'combobox', 'link', 'menuitem', 'option', 'checkbox', 'radio', 'slider', 'tab', 'switch'}
            prioritized_roles = [r.lower().strip() for r in prioritized_roles_raw if isinstance(r, str) and r.lower().strip() in valid_roles]
        
        if prioritized_roles:
            logger.info(f"  🎯 Prioritized roles for next iteration: {', '.join(prioritized_roles)}")
        else:
            logger.info(f"  (No prioritized roles suggested)")

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
            logger.warning(f"  ⚠️  OVERRIDE: Goal marked complete by LLM, but required values not typed: {missing_values}")
            logger.warning(f"  Forcing goal_reached=False due to missing typed values")
            goal_reached = False
            reasoning = f"Required value(s) '{', '.join(missing_values)}' must be entered but were not found in action history. " + reasoning
            confidence = min(confidence, 0.3)  # Lower confidence

    logger.info(f"  Goal reached: {goal_reached} (confidence: {confidence:.1%})")
    if reasoning:
        logger.info(f"  Reasoning: {reasoning}")
    if missing_steps:
        try:
            logger.info(f"  Missing steps: {', '.join(map(str, missing_steps))}")
        except Exception:
            logger.info("  Missing steps: (unprintable)")

    # Handle multiple goals: if current goal is complete, advance to next goal
    result_updates = {'goal_reached': goal_reached}
    
    # Store prioritized roles if goal is not reached (clear if reached)
    if goal_reached:
        result_updates['prioritized_roles'] = []  # Clear when goal is reached
    elif prioritized_roles:
        result_updates['prioritized_roles'] = prioritized_roles  # Set new prioritized roles
    
    if multiple_goals and current_goal and goal_reached:
        try:
            current_index = multiple_goals.index(current_goal)
            if current_index < len(multiple_goals) - 1:
                # Advance to next goal
                next_goal = multiple_goals[current_index + 1]
                logger.info(f"\n  ✓ Goal {current_index + 1}/{len(multiple_goals)} completed!")
                logger.info(f"  → Advancing to next goal {current_index + 2}/{len(multiple_goals)}: {next_goal}")
                
                # Keep only the last action_history entry, remove all others
                action_history = state.get('action_history') or []
                if len(action_history) > 0:
                    trimmed_history = [action_history[-1]]  # Keep only last entry
                    result_updates['action_history'] = trimmed_history
                    logger.info(f"  → Cleared action history, keeping only last entry (total entries removed: {len(action_history) - 1})")
                
                result_updates['current_goal'] = next_goal
                # Don't mark overall goal as reached until all goals are done
                result_updates['goal_reached'] = False
            else:
                # All goals are complete
                logger.info(f"\n  ✓ All {len(multiple_goals)} goals completed!")
                result_updates['goal_reached'] = True
        except (ValueError, IndexError):
            # current_goal not found in multiple_goals, keep as is
            pass
    
    return result_updates


