from typing import Any, Dict, Optional, List
import json

from ..state import AgentState
from ..utils.json_parser import extract_json_payload
from .common import client


def _build_dynamic_evaluation_context(state: AgentState, last_action: Optional[Dict[str, Any]]) -> str:
    """Build dynamic context hints for evaluation (Option 6: dynamic prompting)."""
    hints = []
    step_count = state.get('step_count', 0)
    errors = state.get('errors') or []
    action_history = state.get('action_history') or []
    interactables = state.get('interactable_elements') or []
    
    # Context: Completion confidence indicators
    if last_action:
        action_type = last_action.get('type', '')
        action_label = (last_action.get('label') or '').lower()
        
        # High-confidence completion signals
        completion_keywords = ['submit', 'confirm', 'send', 'done', 'complete', 'finish', 'save']
        if action_type == 'click' and any(kw in action_label for kw in completion_keywords):
            hints.append("✅ COMPLETION SIGNAL: Last action was a submission/confirmation control. This strongly suggests task completion. Verify goal alignment, then consider marking as complete.")
        
        # Data entry completion
        if action_type == 'type' and step_count > 3:
            # Check if subsequent actions suggest completion workflow
            has_subsequent_clicks = any(
                a.get('type') == 'click' for a in action_history[-3:]
            )
            if not has_subsequent_clicks:
                hints.append("ℹ️ DATA ENTRY: Recent typing action detected. Check if required fields are filled and if auto-save or explicit submission is needed.")
    
    # Context: Error state
    if errors:
        hints.append(f"⚠️ ERRORS PRESENT: Validation or runtime errors detected ({len(errors)} errors). Task likely incomplete until errors are resolved.")
    
    # Context: Step count indicators
    if step_count < 3:
        hints.append("🔍 EARLY STAGE: Very few steps taken. Unless goal is trivial, task is likely incomplete. Look for initial progress indicators.")
    elif step_count > 20:
        hints.append("⚠️ MANY STEPS: High step count suggests either complex task or potential inefficiency. Re-evaluate if goal requires this many steps or if agent is stuck.")
    
    # Context: UI state indicators
    has_submit_controls = any(
        'submit' in (elem.get('label') or '').lower() or
        'confirm' in (elem.get('label') or '').lower() or
        (elem.get('role') == 'button' and 
         any(term in (elem.get('label') or '').lower() for term in ['done', 'complete', 'finish', 'save']))
        for elem in interactables
    )
    if has_submit_controls and not errors:
        hints.append("ℹ️ SUBMISSION AVAILABLE: Submit/confirmation controls are visible and no errors present. If goal-aligned actions are complete, task may be done (some apps require explicit submission, others auto-save).")
    
    return '\n'.join(hints) if hints else ""


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether the goal is complete using LLM with robust, app-agnostic criteria."""
    print(f"\n[CHECK GOAL] Evaluating goal completion")
    print(f"  Goal: {state.get('goal', '')}")
    print(f"  Steps taken: {state.get('step_count', 0)}")

    model_name = state.get('llm_model') or "gpt-4o"
    recent_actions = (state.get('action_history') or [])[-10:]

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

    last_action = action_details[-1] if action_details else None
    if last_action:
        text_part = f" with text '{last_action['text']}'" if last_action.get('text') else ""
        print(f"  Last action: {last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})")

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_evaluation_context(state, last_action)
    
    # Create compact UI state summary instead of sending full interactable list
    # (Full list already sent in scoring node, no need to duplicate)
    interactables_full = state.get('interactable_elements', [])
    ui_state_summary = {}
    if interactables_full:
        # Count elements by type
        role_counts = {}
        submit_buttons = []
        for elem in interactables_full:
            role = elem.get('role', 'unknown')
            role_counts[role] = role_counts.get(role, 0) + 1
            
            # Track submit/confirmation buttons
            label = (elem.get('label') or '').lower()
            if any(term in label for term in ['submit', 'send', 'confirm', 'save', 'done', 'complete', 'finish']):
                submit_buttons.append({
                    'label': elem.get('label', ''),
                    'disabled': elem.get('disabled', False)
                })
        
        ui_state_summary = {
            'total_elements': len(interactables_full),
            'elements_by_role': role_counts,
            'submit_buttons': submit_buttons[:5] if submit_buttons else []  # Limit to top 5
        }

    # Build structured prompt with clear sections (Option 2)
    prompt = f"""# ROLE & OBJECTIVE
You are an autonomous web agent's evaluation module. Your task is to assess whether the user's goal has been completed based on action history, current UI state, and goal alignment.

# CONTEXT
Goal: {state.get('goal', '')}
Instruction: {state.get('instruction', '')}
Current URL: {state.get('current_url', '')}
Steps Taken: {state.get('step_count', 0)}

Errors/Validation Issues:
{json.dumps(state.get('errors', [])) if state.get('errors') else "None"}

{"## DYNAMIC CONTEXT HINTS" + chr(10) + dynamic_hints + chr(10) if dynamic_hints else ""}
# ACTION HISTORY

Most Recent Action:
{json.dumps(last_action) if last_action else "None"}

Complete Action History (chronological, last 10):
{json.dumps(action_details)}

# CURRENT UI STATE
UI State Summary:
{json.dumps(ui_state_summary) if ui_state_summary else "No interactable elements available"}

# EVALUATION PRINCIPLES

## Completion Evidence (CRITICAL)
- Favor completion when a coherent workflow of actions aligns with the goal
- Consider typed values matching goal parameters as strong evidence
- No validation or runtime errors should be present for confident completion
- Submission/confirmation actions (submit, confirm, send) are strong completion signals

## Auto-Save vs Explicit Submission (IMPORTANT)
- Many modern apps auto-save: absence of explicit submit does not always imply incompletion
- If a visible submission control remains, consider whether it's required or optional
- Balance between over-caution (requiring unnecessary submits) and premature completion

## Confidence Levels
- 0.9-1.0 = Very confident: Clear completion signals, goal-aligned actions, no errors
- 0.7-0.89 = Confident: Strong evidence but minor uncertainties
- 0.5-0.69 = Moderate: Some evidence but significant uncertainty
- 0.0-0.49 = Low: Insufficient evidence or contradictory signals

## Rationale Requirements
- Provide concise, evidence-based explanation referencing specific actions
- Reference the goal explicitly in your reasoning
- If incomplete, list concrete missing steps (be specific, not generic)

# OUTPUT FORMAT
Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "2-4 sentence evidence-based explanation referencing specific actions and goal alignment",
  "confidence": 0.0-1.0,
  "missing_steps": ["specific next steps if not complete, or empty array if complete"]
}}"""

    system_message = """You are an autonomous web agent's evaluation module. Your role is to assess task completion based on action history, UI state, and goal alignment. You must be balanced: neither over-cautious nor premature in declaring completion. Return only valid JSON following the specified format."""
    
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ]
        )
        content = (response.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"  Evaluation LLM call failed: {e}")
        return {'goal_reached': False}

    result = extract_json_payload(content) or {}
    goal_reached = bool(result.get('goal_reached', False))
    reasoning = (result.get('reasoning') or 'Unknown').strip()
    try:
        confidence = float(result.get('confidence', 0.5))
    except Exception:
        confidence = 0.5
    missing_steps = result.get('missing_steps', []) or []

    print(f"  Goal reached: {goal_reached} (confidence: {confidence:.1%})")
    if reasoning:
        print(f"  Reasoning: {reasoning}")
    if missing_steps:
        try:
            print(f"  Missing steps: {', '.join(map(str, missing_steps))}")
        except Exception:
            print("  Missing steps: (unprintable)")

    return { 'goal_reached': goal_reached }


