"""LangGraph nodes for the autonomous web agent."""
from typing import Any, Dict, List
import json
import requests
from openai import OpenAI
from .state import AgentState, ScoredAction
from .utils.dom import summarize_accessibility_tree
from dotenv import load_dotenv

# Load environment variables from .env (if present) before initializing OpenAI
load_dotenv()

# Initialize OpenAI client (reads OPENAI_API_KEY from env)
client = OpenAI()

# Driver API base URL
DRIVER_URL = "http://127.0.0.1:3999"


def bootstrap_node(state: AgentState) -> Dict[str, Any]:
    """Infer base URL and app from instruction, init driver, and set goal.

    This enables instruction-only runs without explicit goal/URL flags.
    """
    instruction = state.get('instruction') or state.get('goal') or ''
    print(f"\n[BOOTSTRAP] Inferring app and base URL from instruction: '{instruction}'")

    prompt = f"""Given the user's instruction, infer the most likely web application and base URL to start from.

Instruction: "{instruction}"

Return ONLY a JSON object with:
{{
  "app_name": "Readable app name, e.g., Linear, Notion, GitHub",
  "base_url": "Canonical login/home URL, e.g., https://linear.app, https://www.notion.so/",
  "normalized_goal": "A concise restatement of the user's goal"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Infer target app and base URL for web automation. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    app_name = ""
    base_url = ""
    normalized_goal = instruction
    try:
        parsed = json.loads(content)
        app_name = parsed.get('app_name') or ""
        base_url = parsed.get('base_url') or ""
        normalized_goal = parsed.get('normalized_goal') or instruction
    except Exception:
        pass

    if not base_url:
        raise RuntimeError("Failed to infer base URL from instruction. Please specify a URL.")

    # Initialize driver at inferred base URL
    try:
        resp = requests.post(f"{DRIVER_URL}/init", json={
            'app': app_name or 'WebApp',
            'url': base_url,
        }, timeout=30)
        rj = resp.json()
        if not rj.get('ok'):
            raise RuntimeError(rj.get('error') or 'Driver init failed')
        print(f"  ✓ Driver initialized at {base_url}")
    except Exception as e:
        print(f"  ❌ Driver init error: {e}")
        return { 'error': str(e) }

    return {
        'goal': normalized_goal,
        'app_name': app_name or 'WebApp',
        'base_url': base_url,
        'current_url': base_url,
    }


def observe_node(state: AgentState) -> Dict[str, Any]:
    """Observe the current page state via the driver."""
    print(f"\n[OBSERVE] Step {state['step_count']}")
    
    # Get current page state
    resp = requests.post(f"{DRIVER_URL}/observe")
    data = resp.json()
    
    # Capture screenshot
    screenshot_resp = requests.get(f"{DRIVER_URL}/screenshot")
    screenshot_bytes = screenshot_resp.content
    
    # Update state
    updates = {
        'current_url': data['url'],
        'dom_snapshot': data['a11y'],
        'interactable_elements': data['interactables'],
        'errors': data.get('errors') or [],
        'screenshot_bytes': screenshot_bytes,
        'screenshots': state['screenshots'] + [screenshot_bytes],
    }
    
    print(f"  URL: {data['url']}")
    print(f"  Found {len(data['interactables'])} interactable elements")
    if data.get('errors'):
        print(f"  ⚠️  Errors detected: {data['errors']}")
    
    return updates


# (Removed synthesis; LLM drives all actions.)

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

**Goal**: {state['goal']}
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
     * Body fields: "Description", "Content", "Start typing", "Write something", contenteditable areas
   - For goals with multiple data points (e.g., "create page X with content Y"):
     * Propose SEPARATE type actions for title field (text=X) and body field (text=Y)
     * Both should score high (9-10) as both are critical steps

4. **SEMANTIC MATCHING** (align element labels with goal keywords):
   - If goal mentions "project", prioritize elements containing "project"
   - If goal mentions "comment", prioritize comment textboxes and post buttons
   - If goal mentions "status" or "filter", prioritize status dropdowns and filter controls
   - Example: Goal "assign to kgen" → "Assignee" dropdown scores 9-10

5. **SCROLL FOR DISCOVERY** (score moderately when stuck or incomplete view):
   - If NO high-quality action candidates visible (no obvious buttons/fields), propose scroll
   - Scroll reveals hidden UI elements (long lists, below-fold content, dropdown options)
   - Use: selector="window", label="Scroll down", action_type="scroll", score=6-7
   - Purpose: exploration when direct path isn't visible

6. **AVOID REPETITION**:
   - Check recent actions - don't propose the same action twice unless necessary
   - If an action was already tried without progress, reduce its score

7. **EXTRACT GOAL DATA COMPLETELY**:
   - Parse goal for ALL text/data that needs to be entered
   - Example: "create page called Daily Note and write Softlight Engineering Assignment"
     * Title to type: "Daily Note"
     * Content to type: "Softlight Engineering Assignment"
   - Propose type actions with the EXACT text from the goal

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
    filtered_scored: List[ScoredAction] = [a for a in scored if _action_key_from_scored(a) not in tried_here]
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

Goal: {state['goal']}
Current URL: {state['current_url']}
Errors/Validation: {json.dumps(errors)}
Recent actions (last 5): {json.dumps(recent)}

Candidates (choose one by index 'i'):
{json.dumps(candidates, indent=2)}

DECISION STRATEGY:
You must balance two competing needs:

1. **EXPLOITATION** (using high-scored actions):
   - When you see a high-scored action (≥7.0) that directly advances the goal, strongly prefer it
   - High scores mean the action is semantically aligned with the goal
   - Exploit clear opportunities to make progress

2. **EXPLORATION** (discovering new options):
   - When ALL candidates have low scores (<5.0), it means nothing obvious advances the goal
   - In this case, PREFER scroll/exploratory actions to discover new UI elements
   - Clicking poor-scored actions (score < 5.0) is likely to waste steps or move in wrong direction
   - Scroll is especially valuable when: stuck in same place, no high-quality options visible, or repeated low scores
   
3. **ERROR RECOVERY**:
   - If validation errors exist, prioritize actions that address them (e.g., fill required fields)
   - Errors indicate the last action was incomplete - look for what's missing

4. **AVOID LOOPS**:
   - Check recent action history - don't repeat ineffective patterns
   - If you've tried high-scored actions without progress, switch to exploration
   - Sometimes a strategic scroll or menu opening unlocks the next step

5. **QUALITY AWARENESS**:
   - Be honest about candidate quality in your rationale
   - If max score is <5.0, acknowledge options are weak
   - Don't pretend a score-3.0 action is good - use it only if exploration exhausted

STRATEGIC EXAMPLES:
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


def execute_action_node(state: AgentState) -> Dict[str, Any]:
    """Execute the highest-scored action."""
    action = state['next_action']
    
    if not action:
        print(f"\n[EXECUTE] No action to execute")
        return {'error': 'No valid action found'}
    
    print(f"\n[EXECUTE] {action.action_type} on '{action.label}' (score: {action.score:.1f})")
    print(f"  Reasoning: {action.reasoning}")
    
    # Build action payload
    payload = {
        'type': action.action_type,
        'selector': action.selector,
    }
    
    if action.action_type == 'type' and action.text:
        payload['text'] = action.text
    
    # Capture a focused screenshot around the target (with padding) before executing
    try:
        if action.selector and action.action_type in ('click', 'type'):
            crop_resp = requests.post(f"{DRIVER_URL}/screenshot_region", json={
                'selector': action.selector,
                'margin': 24,
            }, timeout=10)
            if crop_resp.status_code == 200 and crop_resp.content:
                # Append focused image to screenshots list
                focused_bytes = crop_resp.content
                screenshots = state.get('screenshots') or []
                screenshots = screenshots + [focused_bytes]
                # Track that this focused screenshot corresponds to the current step index
                focused_after_steps = set(state.get('focused_after_steps') or [])
                focused_after_steps.add(state.get('step_count', 0))
            else:
                screenshots = state.get('screenshots') or []
                focused_after_steps = set(state.get('focused_after_steps') or [])
        else:
            screenshots = state.get('screenshots') or []
            focused_after_steps = set(state.get('focused_after_steps') or [])
    except Exception:
        screenshots = state.get('screenshots') or []
        focused_after_steps = set(state.get('focused_after_steps') or [])

    # Execute via driver
    try:
        resp = requests.post(f"{DRIVER_URL}/act", json=payload, timeout=15)
        result = resp.json()
        
        if not result.get('ok'):
            print(f"  ❌ Action failed: {result.get('error')}")
            return {
                'error': result.get('error'),
                'stuck_count': state['stuck_count'] + 1
            }
        
        print(f"  ✓ Action executed successfully")
        
        # Add to history (include text for type actions so we can verify content later)
        action_record = {
            'type': action.action_type,
            'selector': action.selector,
            'label': action.label,
            'score': action.score,
            'reasoning': action.reasoning,
        }
        if action.action_type == 'type' and action.text:
            action_record['text'] = action.text
        
        # Record this action as tried for the current URL to avoid repeating it
        current_url = state.get('current_url') or ''
        tried_map = dict(state.get('tried_actions_by_url') or {})
        tried_here = list(tried_map.get(current_url, []))
        action_key = _action_key_from_scored(action)
        if action_key not in tried_here:
            tried_here.append(action_key)
        tried_map[current_url] = tried_here
        
        return {
            'action_history': state['action_history'] + [action_record],
            'step_count': state['step_count'] + 1,
            'stuck_count': 0,
            'tried_actions_by_url': tried_map,
            'screenshots': screenshots,
            'focused_after_steps': list(focused_after_steps),
        }
        
    except Exception as e:
        print(f"  ❌ Exception during action: {e}")
        return {
            'error': str(e),
            'stuck_count': state['stuck_count'] + 1
        }


def check_goal_node(state: AgentState) -> Dict[str, Any]:
    """Use LLM to check if we've reached the goal - PURE LLM EVALUATION, NO HEURISTICS."""
    print(f"\n[CHECK GOAL] LLM evaluating goal completion...")
    
    # Build detailed context for LLM
    recent_actions = state['action_history'][-10:]  # Show more history for better evaluation
    
    # Include full action details with text content
    action_details = []
    for a in recent_actions:
        detail = {
            'type': a['type'],
            'label': a.get('label', ''),
            'text': a.get('text', '')  # Include typed text for verification
        }
        action_details.append(detail)
    
    prompt = f"""Evaluate whether the goal has been achieved based on the complete action history and current state.

**Goal**: {state['goal']}
**Current URL**: {state['current_url']}
**Steps Taken**: {state['step_count']}
**App**: {state.get('app_name', 'Unknown')}
**Errors**: {json.dumps(state.get('errors', []))}

**Complete Action History** (chronological order):
{json.dumps(action_details, indent=2)}

EVALUATION STRATEGY:
Analyze the action sequence to determine if the goal is TRULY complete. Use these patterns:

1. **COMMENTING GOALS** (e.g., "post a comment", "comment hi on video"):
   - Look for: type action into comment box + click "Comment"/"Post" button
   - Success pattern: typed text → clicked submit WITHOUT errors
   - If you see this sequence completed, goal is reached
   - Example: typed "hi" into comment textbox, clicked "Comment" → SUCCESS

2. **PAGE/NOTE CREATION GOALS** (e.g., "create page titled X with content Y"):
   - Look for: type action for TITLE + type action for BODY/CONTENT
   - In Notion/docs apps, there are usually TWO separate type actions:
     * First type: page title (e.g., "Daily Note")
     * Second type: page body content (e.g., "This is great")
   - Success pattern: both title AND body typed WITHOUT errors
   - If goal specifies both title and content, BOTH must be present in action history
   - Example: typed "Daily Note" (title), typed "Softlight Engineering..." (content) → SUCCESS

3. **PROJECT/ITEM CREATION** (e.g., "create project called X"):
   - Look for: clicked "Create"/"New" → typed name → clicked "Save"/"Create"
   - Success pattern: opened creation flow + filled required fields + submitted
   - May involve multiple type actions for different fields (name, description, etc.)

4. **FILTER/NAVIGATION GOALS** (e.g., "filter by in-progress", "go to all issues"):
   - Look for: navigated to section + applied filter/opened menu
   - Success pattern: reached target view (URL change or UI state change)
   - May involve clicks on menus, dropdowns, filter buttons

5. **STATUS CHANGE GOALS** (e.g., "change status to done"):
   - Look for: opened status menu + clicked desired status option
   - Success pattern: clicked item → clicked status dropdown → selected target status
   - Multiple clicks in sequence indicate status change flow

6. **GENERAL CRITERIA**:
   - All goal components must be addressed (if goal says "A and B", both A and B must be done)
   - No outstanding errors that invalidate the work
   - Sufficient evidence in action sequence (don't assume - verify from actions)
   - Be realistic: if standard workflow completed without errors, likely success

7. **CONFIDENCE LEVELS**:
   - 0.9-1.0: All steps clearly completed, strong evidence
   - 0.7-0.8: Most steps done, minor uncertainty
   - 0.5-0.6: Partial completion, significant steps missing
   - 0.0-0.4: Goal not reached or too early to tell

BE SPECIFIC: Check action history for exact evidence. Don't assume - verify.

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


def should_continue(state: AgentState) -> str:
    """Routing function to decide next step."""
    # Check stopping conditions
    if state.get('goal_reached'):
        return "end"
    
    if state['step_count'] >= state['max_steps']:
        print(f"\n⚠️  Max steps ({state['max_steps']}) reached")
        return "end"
    
    if state.get('stuck_count', 0) >= 2:
        print(f"\n⚠️  Agent appears stuck (failed actions: {state['stuck_count']})")
        return "end"
    
    # Do not end immediately on transient errors; keep going unless stuck/max_steps/goal.
    if state.get('error'):
        print(f"\n⚠️  Error encountered (continuing): {state['error']}")
        # Clear error so it doesn't spam subsequent iterations
        return "continue"
    
    return "continue"

