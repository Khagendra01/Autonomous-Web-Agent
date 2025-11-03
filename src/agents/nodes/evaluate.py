from typing import Any, Dict, Optional, List
import json

from ..state import AgentState
from ..utils.logger import get_logger
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
    if step_count > 20:
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


def _build_sub_task_verification_section(sub_tasks: List[Dict[str, Any]]) -> str:
    """Build the sub-task verification section for the evaluation prompt."""
    sub_task_summary = []
    for st in sub_tasks:
        sub_task_summary.append({
            "id": st.get('id', ''),
            "description": st.get('description', ''),
            "type": st.get('type', ''),
            "status": st.get('status', 'pending'),
            "required_context": st.get('required_context', 'any'),
            "verification_patterns": st.get('verification_patterns', []),
            "evidence": st.get('evidence', [])
        })
    return "## SUB-TASK VERIFICATION\nBelow are the parsed sub-tasks that must ALL be completed. Verify each one separately:\n" + json.dumps(sub_task_summary, indent=2) + "\n\n"


def _update_sub_task_evidence(
    sub_tasks: List[Dict[str, Any]], 
    action_history: List[Dict[str, Any]], 
    current_url: str
) -> List[Dict[str, Any]]:
    """Update sub-task evidence based on action history. Does NOT auto-mark as complete - LLM evaluation decides."""
    updated = []
    
    for task in sub_tasks:
        task_copy = task.copy()
        evidence = task_copy.get('evidence', [])
        
        # Check if task is already marked completed (by LLM evaluation)
        if task_copy.get('status') == 'completed':
            updated.append(task_copy)
            continue
        
        # Check each action for matching verification patterns
        required_context = task_copy.get('required_context', 'any')
        verification_patterns = task_copy.get('verification_patterns', [])
        
        for action in action_history:
            action_label = (action.get('label') or '').lower()
            action_type = action.get('type', '')
            action_url = action.get('url', '')  # Use URL where action occurred, not current URL
            
            # Check if action matches verification patterns
            matches_pattern = False
            if verification_patterns:
                # Use the URL where the action actually occurred
                combined_text = f"{action_label} {action_url}".lower()
                matches_pattern = any(
                    pattern.lower() in combined_text 
                    for pattern in verification_patterns
                )
            
            # Check if context matches using the URL where action occurred
            context_matches = _check_context_match(required_context, action_url, action)
            
            # If pattern matches and context is correct, add evidence
            # But don't auto-mark as complete - let LLM evaluation decide
            if matches_pattern and context_matches:
                # Check if this action is already in evidence
                action_key = f"{action_type}|{action_label}"
                existing = any(
                    e.get('action_key') == action_key 
                    for e in evidence
                )
                if not existing:
                    evidence.append({
                        'action_key': action_key,
                        'action_type': action_type,
                        'label': action_label,
                        'url': action_url,  # Store the URL where action occurred
                        'step': action_history.index(action) if action in action_history else -1
                    })
        
        task_copy['evidence'] = evidence
        # DO NOT auto-mark as completed - let LLM evaluation decide based on evidence
        
        updated.append(task_copy)
    
    return updated


def _check_context_match(required_context: str, action_url: str, action: Dict[str, Any]) -> bool:
    """Check if the URL where action occurred matches required context."""
    if required_context == 'any':
        return True
    
    if not action_url:
        # If no URL stored, can't verify context - be conservative
        return False
    
    url_lower = action_url.lower()
    
    if required_context == 'list_view':
        # List views typically have patterns like /issues, /projects, /list, etc.
        # Avoid detail views like /issue/123, /project/abc
        list_patterns = ['/issues', '/projects', '/list', '/my-issues', '/active', '/team/']
        detail_patterns = ['/issue/', '/project/', '/detail', '/view/']
        
        has_list_pattern = any(p in url_lower for p in list_patterns)
        has_detail_pattern = any(p in url_lower for p in detail_patterns)
        
        # Must have list pattern AND not have detail pattern
        return has_list_pattern and not has_detail_pattern
    
    elif required_context == 'detail_view':
        # Detail views typically have /issue/123, /project/abc patterns
        detail_patterns = ['/issue/', '/project/', '/detail', '/view/']
        return any(p in url_lower for p in detail_patterns)
    
    elif required_context == 'modal':
        # Modals are harder to detect from URL alone - URLs often don't change
        # For now, if URL doesn't change but modal likely opened, we can't verify
        # Return True to allow evidence collection, LLM will verify
        return True
    
    elif required_context == 'form':
        # Forms could be in modals or separate pages
        # Return True to allow evidence collection, LLM will verify
        return True
    
    return True


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Evaluate whether the goal is complete using LLM with robust, app-agnostic criteria."""
    logger = get_logger()
    if logger:
        logger.log("Evaluating goal completion", "INFO")
        logger.log(f"Goal: {state.get('goal', '')}", "INFO")
        logger.log(f"Steps taken: {state.get('step_count', 0)}", "INFO")

    # Prevent duplicate evaluation within the same step
    step_now = int(state.get('step_count', 0))
    last_eval = state.get('last_evaluated_step')
    if isinstance(last_eval, int) and last_eval == step_now:
        # Return current known status without re-evaluating
        return {
            'goal_reached': bool(state.get('goal_reached', False)),
            'sub_tasks': state.get('sub_tasks') or [],
            'current_sub_task_index': int(state.get('current_sub_task_index', 0)),
            'last_evaluated_step': step_now,
        }

    model_name = state.get('llm_model') or "gpt-4.1"
    
    # Deterministic predicate check: pre-mark status_change sub-task complete if predicate truth observed
    predicate_truths = state.get('predicate_truths') or {}
    if predicate_truths:
        existing_sub_tasks = state.get('sub_tasks') or []
        for task in existing_sub_tasks:
            if task.get('type') == 'status_change' and predicate_truths.get('statusIsDone', False):
                task['status'] = 'completed'
    recent_actions = (state.get('action_history') or [])[-10:]

    # Normalize action details (compact) for evaluation (include URL for context verification)
    action_details: List[Dict[str, Any]] = []
    for a in recent_actions[-5:]:
        action_details.append({
            't': a.get('type', ''),
            'l': a.get('label', ''),
            'u': a.get('url', ''),
        })

    # For last_action in hints, build from original detailed last entry if present
    last_action = None
    if recent_actions:
        last_raw = recent_actions[-1]
        last_action = {
            'type': last_raw.get('type', ''),
            'label': last_raw.get('label', ''),
            'url': last_raw.get('url', ''),
        }
        print(f"  Last action: {last_action['type']} on '{last_action['label']}'")

    # Build dynamic context hints (Option 6)
    dynamic_hints = _build_dynamic_evaluation_context(state, last_action)
    
    # Get sub-tasks for verification
    sub_tasks = state.get('sub_tasks') or []
    
    # Update sub-task evidence based on action history
    if sub_tasks:
        sub_tasks = _update_sub_task_evidence(sub_tasks, recent_actions, state.get('current_url', ''))
    
    # Get currently available scored actions from the scoring node (high-value next steps)
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
            })
    
    # Deterministic gates
    errors_present = bool(state.get('errors'))
    high_value_remaining = any((a.get('score') or 0) >= 8 for a in available_high_scoring_actions)
    all_subtasks_completed = bool(sub_tasks) and all(t.get('status') == 'completed' or (t.get('evidence') and len(t.get('evidence')) > 0) for t in sub_tasks)
    
    # Fingerprint-based reuse: if fingerprint unchanged and no high-value actions remain, reuse prior decision
    current_fp = state.get('interactable_fingerprint') or ""
    last_eval_fp = state.get('last_evaluation_fingerprint') or ""
    if current_fp and last_eval_fp and current_fp == last_eval_fp and not high_value_remaining:
        if logger:
            logger.log("Evaluation skipped (fingerprint unchanged, no high-value actions)", "INFO")
        return {
            'goal_reached': bool(state.get('goal_reached', False)),
            'sub_tasks': sub_tasks,
            'current_sub_task_index': int(state.get('current_sub_task_index', 0)),
            'last_evaluated_step': step_now,
            'last_evaluation_fingerprint': current_fp,
        }

    # Auto-incomplete gate
    if errors_present or high_value_remaining:
        if logger:
            logger.log("Auto-eval: Incomplete (errors present or high-scoring actions remain)", "INFO")
        return {
            'goal_reached': False,
            'sub_tasks': sub_tasks,
            'current_sub_task_index': state.get('current_sub_task_index', 0),
            'last_evaluated_step': step_now,
            'last_evaluation_fingerprint': current_fp,
        }

    # Auto-complete gate
    if all_subtasks_completed and not errors_present and not high_value_remaining:
        if logger:
            logger.log("Auto-eval: Complete (all sub-tasks evidenced, no blockers)", "SUCCESS")
        return {
            'goal_reached': True,
            'sub_tasks': sub_tasks,
            'current_sub_task_index': len(sub_tasks),
            'last_evaluated_step': step_now,
            'last_evaluation_fingerprint': current_fp,
        }
    
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
            'submit_buttons': submit_buttons[:2] if submit_buttons else []
        }

    # Build conditional sections
    step1_intro = "If sub-tasks are provided above, use them directly. Otherwise, " if not sub_tasks else ""
    
    step2_intro = "CRITICAL: For each sub-task provided above, verify it has specific evidence:\n1. Check if action history contains actions matching verification_patterns\n2. Verify actions happened in required_context (check URL patterns, element roles)\n3. Context mismatch = incomplete (e.g., filtering requires list_view, not detail_view)\n4. Example: \"filter issues\" sub-task with required_context=\"list_view\" cannot be satisfied by clicking \"In Progress\" on detail_view" if sub_tasks else "Check if the action history provides evidence for each required sub-task. Be specific:\n- Typing \"Softlight\" in a name field = evidence for \"enter name\" sub-task\n- Clicking \"assign to kgen\" = evidence for \"assign\" sub-task\n- BUT: clicking a dropdown that opens doesn't mean the selection was made - verify completion"
    
    step4_complete_1 = "ALL sub-tasks have status='completed' with evidence matching verification_patterns AND required_context" if sub_tasks else "All parsed sub-tasks have clear evidence in action history"
    step4_complete_5 = "5. Each sub-task's evidence must be in the correct context (required_context matches where action occurred)\n" if sub_tasks else ""
    
    step4_incomplete_1 = "Any sub-task has status != 'completed' OR evidence doesn't match required_context OR verification_patterns not satisfied" if sub_tasks else "Any required sub-task lacks evidence in action history"
    step4_incomplete_4 = "4. Context mismatch detected (e.g., filter operation attempted on detail_view instead of list_view)\n" if sub_tasks else ""
    
    # Build LAST ACTION pattern match check section for sub-tasks
    last_action_check = ""
    if sub_tasks and last_action:
        last_label = (last_action.get('label') or '').lower()
        matching_sub_tasks = []
        for task in sub_tasks:
            if task.get('status') != 'completed':
                patterns = task.get('verification_patterns', [])
                task_context = task.get('required_context', 'any')
                action_url = last_action.get('url', '')
                # Check if last action matches this task's patterns
                matches_pattern = any(
                    pattern.lower() in last_label 
                    for pattern in patterns
                )
                # Check context match
                context_matches = _check_context_match(task_context, action_url, last_action)
                if matches_pattern and context_matches:
                    matching_sub_tasks.append({
                        'id': task.get('id', ''),
                        'description': task.get('description', ''),
                        'matched_patterns': [p for p in patterns if p.lower() in last_label]
                    })
        
        if matching_sub_tasks:
            last_action_check = f"""## ⚡ LAST ACTION PATTERN MATCH CHECK (CRITICAL - CHECK FIRST)
The MOST RECENT ACTION was: {last_action.get('type', '')} on '{last_action.get('label', '')}'

This action MATCHES verification patterns for the following sub-task(s):
{json.dumps(matching_sub_tasks, indent=2)}

**RULES:**
1. If last action matches a sub-task's verification_patterns AND happened in required_context → that sub-task is COMPLETE
2. Mark matching sub-task(s) as COMPLETED in your sub_task_completions array immediately
3. The action sequence IS the evidence - DO NOT wait for visual proof
4. Example: If last action was "click 'In Progress 3 issues'" and sub-task has verification_patterns=["inprogress", "filter"] → SUB-TASK COMPLETE

**This is the PRIMARY completion signal - use it first before other checks.**

"""
    
    # Build structured prompt (compact sections)
    prompt = f"""# ROLE & OBJECTIVE
You are an autonomous web agent's evaluation module. Assess whether the user's goal has been completed based on compact action history, current UI state, goal alignment, and high-scoring remaining actions.

# CONTEXT
Goal: {state.get('goal', '')}
Instruction: {state.get('instruction', '')}
Current URL: {state.get('current_url', '')}
Steps Taken: {state.get('step_count', 0)}

Errors/Validation Issues:
{json.dumps(state.get('errors', [])) if state.get('errors') else "None"}

{last_action_check}{"## DYNAMIC CONTEXT HINTS\n" + dynamic_hints + "\n" if dynamic_hints else ""}# ACTION HISTORY (compact, last 5)
Keys: t=type, l=label, u=url
{json.dumps(action_details)}

# AVAILABLE HIGH-SCORING ACTIONS (NOT YET EXECUTED)
If high-scoring actions (8+) remain that align with the goal, the task is likely incomplete:
{json.dumps(available_high_scoring_actions) if available_high_scoring_actions else "None"}

# CURRENT UI STATE (compact)
{json.dumps(ui_state_summary) if ui_state_summary else "No interactable elements available"}

{_build_sub_task_verification_section(sub_tasks) if sub_tasks else ""}# EVALUATION METHODOLOGY

## Step 1: Parse Goal Requirements
{step1_intro}Identify ALL required sub-tasks/components.

## Step 2: Verify Action History Against Requirements
{step2_intro}

## Step 3: Check for Remaining High-Scoring Actions
If there are available high-scoring actions (score 8+) that:
- Have NOT been executed yet
- Align with the goal or incomplete sub-tasks
- Then the task is likely INCOMPLETE

## Step 4: Completion Decision
Task is COMPLETE only if:
1. {step4_complete_1}
2. No high-scoring actions (8+) remain that align with incomplete sub-tasks
3. No validation errors present
4. The workflow logically suggests completion
{step4_complete_5}Task is INCOMPLETE if:
1. {step4_incomplete_1}
2. High-scoring actions (8+) exist that align with remaining goal requirements
3. The workflow appears mid-process
{step4_incomplete_4}

# OUTPUT FORMAT
Return ONLY valid JSON:
{{
  "goal_reached": true/false,
  "reasoning": "2-4 sentences explaining evidence and remaining steps",
  "confidence": 0.0-1.0,
  "missing_steps": ["next steps if not complete"]{',\n  "sub_task_completions": [{"id":"task_1","completed":true/false,"reason":"..."} ...]' if sub_tasks else ''}
}}"""

    system_message = """You are an autonomous web agent's evaluation module. Be balanced: neither over-cautious nor premature. Return only valid JSON following the specified format."""
    
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
    
    # Debug: Log raw LLM response for sub-task completions
    sub_task_completions = result.get('sub_task_completions', [])
    if sub_tasks:
        if logger:
            logger.log(f"Sub-tasks evaluation: LLM returned {len(sub_task_completions)} completion decisions", "INFO")
        if not sub_task_completions:
            if logger:
                logger.log("WARNING: LLM did not return sub_task_completions array! Sub-tasks won't be marked complete.", "WARNING")
                logger.log(f"Raw result keys: {list(result.keys())}", "WARNING")
    
    # Process sub-task completions from LLM evaluation (LLM-driven) with persisted-outcome guardrails
    if sub_tasks and sub_task_completions:
        completion_map = {stc.get('id'): stc for stc in sub_task_completions}
        for task in sub_tasks:
            task_id = task.get('id', '')
            if task_id in completion_map:
                llm_decision = completion_map[task_id]
                if llm_decision.get('completed', False):
                    strong_signal = False
                    try:
                        url_now = (state.get('current_url') or '').lower()
                        if any(p in url_now for p in ['/issue/', '/task/', '/project/']):
                            strong_signal = True
                        else:
                            for a in recent_actions[::-1]:
                                lbl = (a.get('label') or '').lower()
                                if any(t in lbl for t in ['currently kgen is assigned', 'done', 'completed', 'status updated']):
                                    strong_signal = True
                                    break
                    except Exception:
                        pass
                    if strong_signal or task.get('type') == 'filter':
                        task['status'] = 'completed'
                        completion_reason = llm_decision.get('reason', '')
                        if logger:
                            logger.log(f"Sub-task '{task.get('description', '')}' marked complete: {completion_reason}", "SUCCESS")
                    else:
                        if logger:
                            logger.log(f"Deferring completion for '{task.get('description', '')}' pending persisted signal", "INFO")
                else:
                    if task.get('status') == 'completed':
                        task['status'] = 'pending'
    
    # If goal is reached, mark all remaining sub-tasks as complete
    if sub_tasks and goal_reached:
        for task in sub_tasks:
            if task.get('status') != 'completed' and task.get('evidence'):
                task['status'] = 'completed'
    
    if logger:
        logger.log(f"Goal reached: {goal_reached} (confidence: {confidence:.1%})", "INFO")
        if reasoning:
            logger.log(f"Reasoning: {reasoning}", "INFO")
    if missing_steps:
        try:
            if logger:
                logger.log(f"Missing steps: {', '.join(map(str, missing_steps))}", "INFO")
        except Exception:
            if logger:
                logger.log("Missing steps: (unprintable)", "WARNING")
    
    # Update current_sub_task_index to point to first incomplete task
    updated_sub_task_index = state.get('current_sub_task_index', 0)
    if sub_tasks:
        for i, task in enumerate(sub_tasks):
            if task.get('status') != 'completed':
                updated_sub_task_index = i
                if i != state.get('current_sub_task_index', 0):
                    if logger:
                        logger.log(f"Active sub-task: {i+1}. {task.get('description', 'N/A')} [{task.get('type', 'N/A')}]", "INFO")
                break
        else:
            # All completed
            updated_sub_task_index = len(sub_tasks)

    return {
        'goal_reached': goal_reached,
        'sub_tasks': sub_tasks,
        'current_sub_task_index': updated_sub_task_index,
        'last_evaluated_step': step_now,
        'last_evaluation_fingerprint': state.get('interactable_fingerprint') or "",
    }


