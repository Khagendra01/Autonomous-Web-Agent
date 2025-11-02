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
    
    # Get currently available scored actions from the scoring node
    # These represent actions that the scoring system identified as high-value for the goal
    scored_actions = state.get('scored_actions') or []
    available_high_scoring_actions = []
    
    # Build set of executed action selectors for comparison
    executed_action_selectors = set()
    for a in recent_actions:
        selector = a.get('selector')
        if selector:
            executed_action_selectors.add(selector)
    
    # Only include actions that haven't been executed yet
    for scored_action in scored_actions[:10]:  # Top 10 scored actions
        if not scored_action or not scored_action.selector:
            continue
        if scored_action.selector not in executed_action_selectors:
            available_high_scoring_actions.append({
                'action_type': scored_action.action_type,
                'label': scored_action.label,
                'selector': scored_action.selector,
                'score': scored_action.score,
                'reasoning': scored_action.reasoning,
                'text': scored_action.text,
            })
    
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
You are an autonomous web agent's evaluation module. Your task is to assess whether the user's goal has been completed based on action history, current UI state, goal alignment, and available next actions.

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

# AVAILABLE HIGH-SCORING ACTIONS (NOT YET EXECUTED)
These are actions that the scoring system identified as valuable for achieving the goal. If high-scoring actions (8+) remain that align with the goal, the task is likely incomplete:
{json.dumps(available_high_scoring_actions) if available_high_scoring_actions else "None - all scored actions have been executed or no actions available"}

# CURRENT UI STATE
UI State Summary:
{json.dumps(ui_state_summary) if ui_state_summary else "No interactable elements available"}

# EVALUATION METHODOLOGY

## Step 1: Parse Goal Requirements
First, analyze the goal and instruction to identify ALL required sub-tasks/components. For example:
- "create a new project called Softlight" → requires: [open project creation, enter name "Softlight", submit/create the project]
- "create issue and assign to kgen" → requires: [create issue, assign to kgen]
- "change name to kgen" → requires: [navigate to profile/settings, change name field to "kgen", save changes]

## Step 2: Verify Action History Against Requirements
Check if the action history provides evidence for each required sub-task. Be specific:
- Typing "Softlight" in a name field = evidence for "enter name" sub-task
- Clicking "assign to kgen" = evidence for "assign" sub-task
- BUT: clicking a dropdown that opens doesn't mean the selection was made - verify completion

## Step 3: Check for Remaining High-Scoring Actions
If there are available high-scoring actions (score 8+) that:
- Have NOT been executed yet (check against action history)
- Align with the goal or incomplete sub-tasks
- Then the task is likely INCOMPLETE - these represent obvious next steps that should be taken

For example:
- If goal requires "create project" and there's a [10.0] "Create project" button visible and not clicked → INCOMPLETE
- If goal requires "assign to kgen" and there's a [9.0] "Change assignee" action not taken → INCOMPLETE
- If high-scoring actions are present but seem unrelated to remaining goal requirements → may still be complete

## Step 4: Completion Decision
Task is COMPLETE only if:
1. All parsed sub-tasks have clear evidence in action history
2. No high-scoring actions (8+) remain that align with incomplete sub-tasks
3. No validation errors present
4. The workflow logically suggests completion (not mid-process)

Task is INCOMPLETE if:
1. Any required sub-task lacks evidence in action history
2. High-scoring actions (8+) exist that align with remaining goal requirements
3. The workflow appears mid-process (e.g., form filled but not submitted, dropdown opened but not selected)

## Auto-Save vs Explicit Submission (IMPORTANT)
- Many modern apps auto-save: absence of explicit submit does not always imply incompletion
- However, if a high-scoring submit/create button (8+) is visible and aligns with the goal, it typically needs to be clicked
- If the goal explicitly requires "create" or "submit" something, and a high-scoring action for that exists, do not assume auto-save
- Balance pragmatism with completeness - err toward requiring obvious final actions when they're highly scored and goal-aligned

## Confidence Levels
- 0.9-1.0 = Very confident: All sub-tasks complete, no high-scoring actions remain, clear completion signals
- 0.7-0.89 = Confident: Strong evidence but minor uncertainties
- 0.5-0.69 = Moderate: Some evidence but significant uncertainty (likely incomplete)
- 0.0-0.49 = Low: Insufficient evidence or contradictory signals (definitely incomplete)

## Rationale Requirements
- Explicitly list the parsed sub-tasks from the goal
- Reference specific actions that provide evidence for each sub-task
- If incomplete, identify which sub-tasks are missing and what high-scoring actions address them
- Be specific, not generic

# OUTPUT FORMAT
Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "2-4 sentence evidence-based explanation. First, list the parsed sub-tasks. Then verify each against action history. Then check if high-scoring actions remain for incomplete sub-tasks.",
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


