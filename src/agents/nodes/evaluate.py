from typing import Any, Dict
import json

from ..state import AgentState
from .common import client


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to check if we've reached the goal - PURE LLM EVALUATION, NO HEURISTICS."""
    print(f"\n[CHECK GOAL] LLM evaluating goal completion...")
    print(f"  Goal: {state['goal']}")
    print(f"  Steps taken: {state['step_count']}")
    
    # Build detailed context for LLM
    recent_actions = state['action_history'][-10:]  # Show more history for better evaluation
    
    # Include full action details with text content
    action_details = []
    for a in recent_actions:
        detail = {
            'type': a['type'],
            'label': a.get('label', ''),
            'text': a.get('text', ''),  # Include typed text for verification
            'score': a.get('score', 0),  # Include the confidence score
            'reasoning': a.get('reasoning', '')  # Include why this action was chosen
        }
        action_details.append(detail)
    
    # Highlight the most recent action for emphasis
    last_action = action_details[-1] if action_details else None
    last_action_summary = "None yet"
    if last_action:
        text_part = f" with text '{last_action['text']}'" if last_action.get('text') else ""
        last_action_summary = f"{last_action['type']} on '{last_action['label']}'{text_part} (score: {last_action.get('score', 0):.1f})"
        print(f"  Last action completed: {last_action_summary}")
    
    prompt = f"""Evaluate whether the goal has been achieved based on the complete action history and current state.

**IMPORTANT**: Give STRONG PRIORITY to determining the task is COMPLETE when the action sequence shows all required steps were executed successfully. Be optimistic about completion - if the actions align with the goal and there are no errors, the task is likely done.

**Goal (normalized)**: {state['goal']}
**Full instruction (verbatim)**: {state.get('instruction', '')}
**Current URL**: {state['current_url']}
**Steps Taken**: {state['step_count']}
**App**: {state.get('app_name', 'Unknown')}
**Errors**: {json.dumps(state.get('errors', []))}

**LAST ACTION JUST COMPLETED** (most recent):
{json.dumps(last_action, indent=2) if last_action else "None"}

**Complete Action History** (chronological order):
{json.dumps(action_details, indent=2)}

EVALUATION STRATEGY:
Analyze the action sequence to determine if the goal is COMPLETE. **DEFAULT TO COMPLETION** when the action patterns match standard workflows and there are no errors.

**BIAS TOWARD COMPLETION**: If you see a logical sequence of actions that would complete the goal in a typical user workflow, and there are NO errors reported, assume the task is DONE. Web apps often update asynchronously, so the absence of errors after completing standard steps indicates success.

1. **COMMENTING GOALS** (e.g., "post a comment", "comment hi on video"):
   - Look for: type action into comment box + click "Comment"/"Post" button
   - Success pattern: typed text → clicked submit WITHOUT errors
   - ✓ If you see this sequence completed → **GOAL IS REACHED**
   - Example: typed "hi" into comment textbox, clicked "Comment" → **SUCCESS** (confidence: 0.95)

2. **PAGE/NOTE CREATION GOALS** (e.g., "create page titled X with content Y"):
   - Look for: type action for TITLE + type action for BODY/CONTENT
   - In Notion/docs apps, there are usually TWO separate type actions:
     * First type: page title (e.g., "Daily Note")
     * Second type: page body content (e.g., "This is great")
   - ✓ Success pattern: both title AND body typed WITHOUT errors → **GOAL IS REACHED**
   - If goal specifies both title and content, BOTH must be present in action history
   - Example: typed "Daily Note" (title), typed "Softlight Engineering..." (content) → **SUCCESS** (confidence: 0.95)

3. **TASK/PROJECT/ITEM CREATION** (e.g., "create task called X", "create project Y"):
   - Look for: clicked "Create"/"New"/"Add" → typed name → (optional: clicked "Save"/"Create")
   - ✓ Success pattern: opened creation flow + filled required fields → **LIKELY COMPLETE**
   - **IMPORTANT**: Many apps auto-save, so submission button click is NOT always required
   - If you see: opened dialog + typed name with HIGH score (8+) + no errors → **GOAL IS REACHED** (confidence: 0.9)
   - Example: clicked "New task", typed "Web Agent" → **SUCCESS** (auto-save assumed)

4. **FILTER/NAVIGATION GOALS** (e.g., "filter by in-progress", "go to section"):
   - Look for: clicked menu/filter/navigation element
   - ✓ Success pattern: clicked target filter/section WITHOUT errors → **GOAL IS REACHED**
   - Example: clicked "In Progress" filter → **SUCCESS** (confidence: 0.9)

5. **STATUS CHANGE GOALS** (e.g., "change status to done", "mark as complete"):
   - Look for: opened status menu + clicked desired status option
   - ✓ Success pattern: clicked item → clicked status dropdown → selected target status → **GOAL IS REACHED**
   - Example: clicked task, clicked status, clicked "Complete" → **SUCCESS** (confidence: 0.95)

6. **DELETION GOALS** (e.g., "delete page X", "remove item Y"):
   - Look for: navigated to item + clicked delete/remove button + (optional: confirmed)
   - ✓ Success pattern: found item + clicked delete WITHOUT errors → **GOAL IS REACHED**
   - Example: clicked "Daily Journal", clicked "Delete", clicked "Confirm" → **SUCCESS**

7. **ASSIGNMENT/INVITE GOALS** (e.g., "assign to X", "invite user Y"):
   - Look for: clicked assignee field + typed/selected user + (optional: clicked save)
   - ✓ Success pattern: opened assignment field + selected user WITHOUT errors → **GOAL IS REACHED**
   - Example: clicked "Assignee", typed "kgen", selected user → **SUCCESS**

8. **GENERAL COMPLETION RULES** (MOST IMPORTANT):
   - ✓ If the LAST ACTION has a HIGH SCORE (≥8.0) and represents a completion step (Submit, Save, Create, Delete, Confirm, etc.), and there are NO errors → **GOAL IS REACHED** (confidence: 0.95)
   - ✓ If all required data from the goal appears in type actions, and there are NO errors → **GOAL IS REACHED** (confidence: 0.9)
   - ✓ If the action sequence follows a standard workflow for the goal type, and there are NO errors → **GOAL IS REACHED** (confidence: 0.85)
   - ✗ Only mark incomplete if: critical steps are clearly missing OR there are validation errors

9. **CONFIDENCE LEVELS** (be optimistic):
   - 0.9-1.0: Standard workflow completed without errors (USE THIS MOST OF THE TIME)
   - 0.7-0.8: Most steps done but minor uncertainty (be generous here)
   - 0.5-0.6: Some progress but key steps missing
   - 0.0-0.4: Very early in the process or wrong direction

**CRITICAL INSTRUCTION**: READ THE ACTION LOG CAREFULLY. If you see a complete workflow executed (e.g., opened form → filled fields → clicked submit) with NO errors, the task is DONE. Don't overthink it - trust the action sequence.

Respond with ONLY a JSON object:
{{
  "goal_reached": true/false,
  "reasoning": "Detailed explanation citing specific actions from history",
  "confidence": 0.0-1.0,
  "missing_steps": ["list any steps that still need to be done, or empty array if complete"]
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at evaluating web automation task completion. Analyze action sequences carefully. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    
    try:
        result = json.loads(content)
        goal_reached = result.get('goal_reached', False)
        reasoning = result.get('reasoning', 'Unknown')
        confidence = result.get('confidence', 0.5)
        missing_steps = result.get('missing_steps', [])
        
        print(f"  ✓ Goal reached: {goal_reached} (confidence: {confidence:.1%})")
        print(f"  Reasoning: {reasoning}")
        if missing_steps:
            print(f"  Missing steps: {', '.join(missing_steps)}")
        
        return {
            'goal_reached': goal_reached
        }
        
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Failed to parse goal check response: {e}")
        return {'goal_reached': False}


