from typing import Any, Dict, List
import json

from ..state import AgentState, ScoredAction
from ..utils.dom import summarize_accessibility_tree
from .common import client


def _action_key_from_scored(action: ScoredAction) -> str:
    # Key prioritizes selector + type which best identifies a unique UI action
    return f"{action.action_type}|{action.selector}"


def score_actions_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to score which actions will lead to the goal."""
    print(f"\n[SCORE] Analyzing actions for goal: {state['goal']}")
    
    # Prepare context for LLM
    dom_summary = summarize_accessibility_tree(state['dom_snapshot'] or {})
    interactables = state['interactable_elements']  # Limit to avoid token overflow
    
    # Build action history summary
    history_summary = []
    for i, action in enumerate(state['action_history'][-5:]):  # Last 5 actions
        history_summary.append(f"{i+1}. {action['type']} on '{action.get('label', 'N/A')}'")
    
    prompt = f"""You are helping navigate a web application to achieve a goal.

**Goal (normalized)**: {state['goal']}
**Full instruction (verbatim)**: {state.get('instruction', '')}
**Current URL**: {state['current_url']}
**App**: {state['app_name']}

**Recent Actions**:
{chr(10).join(history_summary) if history_summary else "None yet"}

**Available Interactive Elements**:
{json.dumps(interactables, indent=2)}

**Task**: Score each element from 0-10 based on how likely acting on it (click, type, or scroll) will help achieve the goal.

SCORING SCALE:
- 10 = Directly achieves the goal or is the next critical step
- 7-9 = Very likely to progress toward the goal
- 4-6 = Might be useful or indirectly related
- 0-3 = Unlikely to help or wrong direction

SCORING STRATEGY (why buttons/elements matter):

1. **ACTION TRIGGER BUTTONS** (score high when goal requires creation/modification):
   - Look for buttons/links with action words: "Create", "New", "Add", "Filter", "Delete", "Edit"
   - These buttons typically OPEN workflows (modals, forms, menus) needed to accomplish goals
   - Example: Goal "create project" → "New project" button scores 9-10 (opens creation flow)
   - Example: Goal "filter by status" → "Filter" button scores 9-10 (opens filter menu)

2. **SUBMISSION BUTTONS** (score high when in a form/modal):
   - When modal/form is open, look for: "Save", "Submit", "Create", "Confirm", "Apply"
   - These buttons FINALIZE workflows after data entry
   - Example: Typed project name, now see "Create" button → score 10 (completes creation)

3. **INPUT FIELDS** (score high when goal requires data entry):
   - Match textbox labels to goal objects (e.g., goal mentions "project name" → "Project name" textbox scores high)
   - Distinguish between TITLE vs BODY fields:
     * Title fields: "Name", "Title", "Project name", "Start typing to edit text"
     * Body fields: "Description", "Content", "Start typing", contenteditable areas
   - For goals with multiple data points (e.g., "create page X with content Y"):
     * Propose SEPARATE type actions for title field (text=X) and body field (text=Y)
     * Both should score high (9-10) as both are critical steps

4. **ENTITY GROUNDING FIRST (CRITICAL)**:
   - If the goal names a specific entity (e.g., a page titled "Daily Journal"), FIRST navigate/open that exact entity before attempting any destructive or context-specific action.
   - Prefer links whose accessible name/text EXACTLY matches the entity. If not visible, prefer using search to locate it.
   - Until the entity is opened (URL or title indicates we are on it), generic menus like "Delete / More" should score LOW.

4. **SEMANTIC MATCHING** (align element labels with goal keywords):
   - If goal mentions "project", prioritize elements containing "project"
   - If goal mentions "comment", prioritize comment textboxes and post buttons
   - If goal mentions "status" or "filter", prioritize status dropdowns and filter controls
   - Example: Goal "assign to kgen" → "Assignee" dropdown scores 9-10

5. **DESTRUCTIVE ACTION SAFETY**:
   - Actions like Delete/Remove/Permanently delete should only score high when the current view clearly refers to the target entity named in the goal.
   - Otherwise, score them low and prefer navigation to the correct entity first.

6. **SCROLL FOR DISCOVERY** (score moderately when stuck or incomplete view):
   - If NO high-quality action candidates visible (no obvious buttons/fields), propose scroll
   - Scroll reveals hidden UI elements (long lists, below-fold content, dropdown options)
   - Use: selector="window", label="Scroll down", action_type="scroll", score=6-7
   - Purpose: exploration when direct path isn't visible

7. **AVOID REPETITION**:
   - Check recent actions - don't propose the same action twice unless necessary
   - If an action was already tried without progress, reduce its score

8. **EXTRACT GOAL DATA COMPLETELY**:
   - Parse BOTH the normalized goal and the full instruction for ALL text/data that needs to be entered
   - Example: "create page called Daily Note and write Softlight Engineering Assignment"
     * Title to type: "Daily Note"
     * Content to type: "Softlight Engineering Assignment"
   - Propose type actions with the EXACT text from the full instruction when present

Return a JSON array with this structure:
[
  {{
    "selector": "role=button[name=\"Create project\"]",
    "label": "Create project",
    "action_type": "click",
    "score": 9.5,
    "reasoning": "This button directly opens the project creation flow"
  }},
  {{
    "selector": "role=textbox[name=\"Project name\"]",
    "label": "Project name",
    "action_type": "type",
    "text": "gamma",
    "score": 10,
    "reasoning": "Entering the required project name aligns with the goal"
  }},
  {{
    "selector": "role=textbox[name=\"Start typing to edit text\"]",
    "label": "Start typing to edit text",
    "action_type": "type",
    "text": "Daily Note",
    "score": 10,
    "reasoning": "Setting the page title to 'Daily Note' as specified in the goal"
  }},
  {{
    "selector": "role=textbox[name=\"Start typing\"], [contenteditable=\"true\"]",
    "label": "Body editor",
    "action_type": "type",
    "text": "This is great",
    "score": 10,
    "reasoning": "Adding the body content 'This is great' to the page as specified in the goal"
  }},
  {{
    "selector": "window",
    "label": "Scroll down",
    "action_type": "scroll",
    "score": 6.5,
    "reasoning": "No high-confidence controls are visible; scroll to reveal more."
  }},
  ...
]

Return ONLY the JSON array, no additional text."""

    # Call OpenAI
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert at web navigation and UI analysis. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
    )
    
    # Parse response
    content = response.choices[0].message.content.strip()
    # Remove markdown code blocks if present
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    
    try:
        scored_actions_raw = json.loads(content)
        scored_actions = [
            ScoredAction(
                action_type=a['action_type'],
                selector=a['selector'],
                label=a['label'],
                score=float(a['score']),
                reasoning=a['reasoning'],
                text=a.get('text')
            )
            for a in scored_actions_raw
        ]

        # Deduplicate by action_type|selector key, keeping the highest-scored instance
        unique_by_key: Dict[str, ScoredAction] = {}
        for a in scored_actions:
            k = _action_key_from_scored(a)
            existing = unique_by_key.get(k)
            if existing is None or a.score > existing.score:
                unique_by_key[k] = a

        deduped: List[ScoredAction] = list(unique_by_key.values())

        # Sort by the LLM-provided score only (no heuristics)
        adjusted: List[ScoredAction] = sorted(deduped, key=lambda x: x.score, reverse=True)

        print(f"  Scored {len(adjusted)} actions (deduped)")
        # Show top 3 as a quick summary
        for i, action in enumerate(adjusted[:3]):
            print(f"  {i+1}. [{action.score:.1f}] {action.action_type} '{action.label}' - {action.reasoning}")

        # Also show the same-score group (within 1.0 of the top score)
        if adjusted:
            top_score = adjusted[0].score
            same_group = [a for a in adjusted if a.score >= top_score - 1.0][:8]
            if len(same_group) > 1:
                print("  Same-score group (±1.0 from top):")
                for a in same_group:
                    suffix = f" → type text='{a.text}'" if (a.action_type == 'type' and a.text) else ""
                    print(f"    - [{a.score:.1f}] {a.action_type} '{a.label}'{suffix}")

        return {
            'scored_actions': adjusted,
            'next_action': None,  # selection is delegated to decide_action_node
        }
    except json.JSONDecodeError as e:
        print(f"  ❌ Failed to parse LLM response: {e}")
        print(f"  Raw response: {content[:200]}")
        return {
            'scored_actions': [],
            'next_action': None,
            'error': f"Failed to parse LLM response: {e}"
        }


