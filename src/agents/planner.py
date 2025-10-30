from typing import Dict, Any
from .state import AgentState
from .knowledge import UIKB
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Planner:
    def __init__(self):
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set. Please create a .env file with OPENAI_API_KEY=your_key")
        self.llm = ChatOpenAI(
            model="gpt-4o",
            api_key=api_key,
            temperature=0.0,
        )
    
    def extract_app_and_url(self, goal: str) -> Dict[str, str]:
        """Use LLM to extract the app name and starting URL from the goal."""
        system_prompt = """You are helping to identify which web application and URL to use based on a user's goal.

Analyze the goal and determine:
1. The app name (short identifier like 'linear', 'notion', 'github', etc.)
2. The starting URL to navigate to

Common apps and their URLs:
- Linear: https://linear.app/
- Notion: https://www.notion.so/
- GitHub: https://github.com/
- Gmail: https://mail.google.com/
- Jira: https://jira.atlassian.com/
- Trello: https://trello.com/
- Slack: https://slack.com/

If the goal mentions a specific URL, use that. Otherwise, infer the most appropriate URL.

Respond in JSON format:
{
  "app": "app_name",
  "url": "https://...",
  "reasoning": "Why you chose this app and URL"
}"""

        user_prompt = f"""Goal: {goal}

What app and URL should be used for this goal?"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            
            if isinstance(content, str):
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                result = json.loads(content)
            else:
                result = content
            
            print(f"[LLM] Extracted app: {result.get('app')}, URL: {result.get('url')}")
            print(f"[LLM] Reasoning: {result.get('reasoning')}")
            
            return {
                'app': result.get('app', 'unknown'),
                'url': result.get('url', 'https://www.google.com'),
                'reasoning': result.get('reasoning', '')
            }
            
        except Exception as e:
            print(f"[ERROR] Failed to extract app/URL from goal: {e}")
            # Fallback to google if extraction fails
            return {
                'app': 'unknown',
                'url': 'https://www.google.com',
                'reasoning': f'Error: {e}'
            }

    def _score_button_relevance(self, button_label: str, button_role: str, goal: str) -> int:
        """Score how relevant a button is to the current goal."""
        if not button_label:
            return 0
        
        label_lower = button_label.lower()
        goal_lower = goal.lower()
        score = 0
        
        # 🎥 YOUTUBE SPECIAL HANDLING: For "play" goals, prioritize video links over search buttons
        if 'youtube' in goal_lower and any(word in goal_lower for word in ['play', 'watch', 'video']):
            # Boost for links (actual videos) vs buttons (search suggestions)
            if button_role == 'link':
                score += 20  # Big boost for video links
            elif button_role == 'button' and 'search' in label_lower:
                score -= 10  # Penalize search suggestion buttons
            
            # Look for video-related indicators in label
            video_indicators = ['official', 'music video', 'mv', 'hd', '4k', 'lyrics', 'full']
            for indicator in video_indicators:
                if indicator in label_lower:
                    score += 5
        
        # Extract key action words from goal
        action_words = []
        if any(word in goal_lower for word in ['create', 'new', 'add', 'make']):
            action_words.extend(['create', 'new', 'add', '+', 'plus'])
        if 'delete' in goal_lower or 'remove' in goal_lower:
            action_words.extend(['delete', 'remove', 'trash'])
        if 'edit' in goal_lower or 'update' in goal_lower:
            action_words.extend(['edit', 'update', 'modify'])
        if 'search' in goal_lower or 'find' in goal_lower:
            action_words.extend(['search', 'find'])
        
        # Extract key object words from goal
        object_words = []
        if 'project' in goal_lower:
            object_words.append('project')
        if 'issue' in goal_lower or 'ticket' in goal_lower:
            object_words.extend(['issue', 'ticket'])
        if 'task' in goal_lower:
            object_words.append('task')
        
        # Score based on action words
        for word in action_words:
            if word in label_lower:
                score += 10
        
        # Score based on object words
        for word in object_words:
            if word in label_lower:
                score += 10
        
        # Boost score for button role (general case)
        if button_role == 'button':
            score += 2
        
        # Boost for exact phrase matches
        if action_words and object_words:
            for action in action_words:
                for obj in object_words:
                    if action in label_lower and obj in label_lower:
                        score += 15  # Big boost for having both
        
        return score
    
    def _analyze_ui_context(self, interactables: list, goal: str) -> dict:
        """Analyze the UI to understand what kind of state we're in."""
        context = {
            'has_inputs': False,
            'input_fields': [],
            'has_submit_buttons': False,
            'submit_buttons': [],
            'is_form_state': False,
            'unfilled_inputs': []
        }
        
        goal_lower = goal.lower()
        
        # Check for input fields
        for item in interactables:
            role = item.get('role', '')
            label = item.get('label', '').lower()
            
            if role in ['textbox', 'searchbox', 'input']:
                context['has_inputs'] = True
                context['input_fields'].append(item)
                
                # Check if this input is relevant to the goal
                # Extract what should be typed (e.g., "named beta" -> "beta")
                if 'named' in goal_lower or 'called' in goal_lower or 'name' in label:
                    context['unfilled_inputs'].append({
                        'field': item,
                        'suggested_value': self._extract_value_from_goal(goal, ['named', 'called', 'name']),
                        'priority': 'high'
                    })
            
            # Check for submit/create buttons
            if role == 'button' and any(word in label for word in ['submit', 'create', 'save', 'add', 'done', 'confirm']):
                context['has_submit_buttons'] = True
                context['submit_buttons'].append(item)
        
        # Determine if we're in a form state
        context['is_form_state'] = context['has_inputs'] and context['has_submit_buttons']
        
        return context
    
    def _extract_value_from_goal(self, goal: str, keywords: list) -> str:
        """Extract the value to enter from the goal."""
        goal_lower = goal.lower()
        for keyword in keywords:
            if keyword in goal_lower:
                # Extract the word after the keyword
                parts = goal_lower.split(keyword)
                if len(parts) > 1:
                    after_keyword = parts[1].strip()
                    # Get the first word/phrase
                    value = after_keyword.split()[0] if after_keyword.split() else ''
                    return value.strip('"\',.!?')
        return ''
    
    def reason_and_plan(self, state: AgentState) -> AgentState:
        """Use LLM to reason about current state and plan next action."""
        obs = state.observation or {}
        interactables = obs.get('interactables', [])
        errors = obs.get('errors', [])
        
        # 🎯 QUICK CHECK: If we're on a YouTube video page for a "play" goal, we're done!
        goal_lower = state.goal.lower()
        current_url = state.current_url or ''
        if any(word in goal_lower for word in ['youtube', 'play', 'watch']) and '/watch?v=' in current_url:
            state.reasoning = "Successfully navigated to YouTube video page. Video is auto-playing."
            state.current_step = "Goal achieved - video is playing"
            state.next_action = {'type': 'none', 'intent': 'Video is already playing'}
            return state
        
        # Analyze UI context
        ui_context = self._analyze_ui_context(interactables, state.goal)
        
        # Query knowledge base for relevant UI elements
        kb = UIKB(state.app)
        relevant_knowledge = []
        seen_items = set()  # Track to avoid duplicates
        
        # Search for relevant semantic actions based on goal keywords
        if any(word in goal_lower for word in ['create', 'add', 'new']):
            for item in kb.query('create'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        if 'filter' in goal_lower:
            for item in kb.query('filter'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        if any(word in goal_lower for word in ['save', 'submit', 'done', 'finish']):
            for item in kb.query('submit'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        if any(word in goal_lower for word in ['delete', 'remove']):
            for item in kb.query('delete'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        if any(word in goal_lower for word in ['edit', 'update', 'modify']):
            for item in kb.query('edit'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        if any(word in goal_lower for word in ['search', 'find']):
            for item in kb.query('search'):
                key = (item.get('role'), item.get('label'))
                if key not in seen_items:
                    relevant_knowledge.append(item)
                    seen_items.add(key)
        
        # Format knowledge hints
        knowledge_hints = ""
        if relevant_knowledge:
            knowledge_hints = "\n\nKnown helpful UI elements from past interactions:\n"
            knowledge_hints += "\n".join([
                f"- {item.get('label')} ({item.get('role')}) - semantic: {', '.join(item.get('semantic', []))}"
                for item in relevant_knowledge[:5]
            ])
        
        # Score and sort interactables by relevance to goal
        scored_interactables = []
        for act in interactables:
            label = act.get('label', '')
            role = act.get('role', 'unknown')
            score = self._score_button_relevance(label, role, state.goal)
            scored_interactables.append((score, act))
        
        # Sort by score (descending)
        scored_interactables.sort(key=lambda x: x[0], reverse=True)
        
        # Format interactables for LLM - show more if stuck in loop
        max_interactables = 50 if state.same_url_action_count >= 3 else 30
        
        # Separate high-priority and normal elements
        high_priority = [item for item in scored_interactables if item[0] > 15]
        normal_priority = [item for item in scored_interactables if item[0] <= 15]
        
        interactables_text = ""
        
        # Show high-priority buttons first with highlighting
        if high_priority:
            interactables_text += "🎯 HIGHLY RELEVANT BUTTONS (these likely match your goal):\n"
            for i, (score, act) in enumerate(high_priority[:10]):
                label = act.get('label', 'no label')
                role = act.get('role', 'unknown')
                selector = act.get('selector', 'N/A')
                interactables_text += f"⭐ {i+1}. {role} - \"{label}\" (selector: {selector})\n"
            interactables_text += "\n"
        
        # Show normal priority buttons
        if normal_priority:
            interactables_text += "Other available elements:\n"
            for i, (score, act) in enumerate(normal_priority[:max_interactables - len(high_priority)]):
                label = act.get('label', 'no label')
                role = act.get('role', 'unknown')
                selector = act.get('selector', 'N/A')
                interactables_text += f"- {i+1}. {role} - \"{label}\" (selector: {selector})\n"
        
        remaining = len(interactables) - len(high_priority) - min(len(normal_priority), max_interactables - len(high_priority))
        if remaining > 0:
            interactables_text += f"\n... and {remaining} more elements"
        
        # Format errors
        errors_text = "\n".join([f"- {err}" for err in errors]) if errors else "None"
        
        # Format UI context analysis
        ui_context_text = ""
        if ui_context['is_form_state']:
            ui_context_text = "\n🎯 WORKFLOW DETECTION: You are in a FORM/DIALOG state!\n"
            ui_context_text += "This means you need to:\n"
            ui_context_text += "1. FILL all required input fields FIRST\n"
            ui_context_text += "2. THEN click the submit/create button\n\n"
            
            if ui_context['unfilled_inputs']:
                ui_context_text += "📝 INPUTS THAT NEED TO BE FILLED:\n"
                for inp in ui_context['unfilled_inputs']:
                    field_label = inp['field'].get('label', 'unnamed field')
                    field_selector = inp['field'].get('selector', 'N/A')
                    suggested_value = inp['suggested_value']
                    ui_context_text += f"   ⚠️ PRIORITY: Fill '{field_label}' with '{suggested_value}' (selector: {field_selector})\n"
                ui_context_text += "\n"
        elif ui_context['has_inputs'] and not ui_context['has_submit_buttons']:
            ui_context_text = "\n💡 UI STATE: Input fields detected, but no submit button visible yet.\n"
            ui_context_text += "You may need to fill inputs first, or scroll to find the submit button.\n\n"
        
        # Detect repeated failures and add strong warning
        failure_warning = ""
        if state.consecutive_failures >= 2:
            failure_warning = f"""
⚠️ CRITICAL: You have failed {state.consecutive_failures} times in a row with '{state.failed_action_type}' actions!
DO NOT REPEAT THE SAME ACTION. You MUST try a completely different approach:
- Look for alternative buttons/elements on the page
- Try scrolling to reveal more options
- Use different interactive elements that you haven't tried yet
- If there's a "skip" or "later" button, consider using it
- Think outside the box and try a different strategy

Available elements you haven't tried yet might include skip buttons, alternative navigation, or other UI controls.
"""
        
        # Detect being stuck in a loop (same URL, successful actions)
        loop_warning = ""
        if state.same_url_action_count >= 3:
            loop_warning = f"""
🔄 LOOP DETECTED: You have performed {state.same_url_action_count} successful actions on the same URL without progress!
You are STUCK. You MUST try something completely different:

IMPORTANT TIPS:
- Button labels may vary: "Create Project" might be "Create new project" or "New Project" or just "+ Project"
- Look for buttons with words like: new, add, create, plus (+)
- Try keyboard shortcuts (some apps use 'C' for create, 'N' for new)
- Look for "+" buttons or icons
- Check if there's a dropdown menu or context menu
- Try scrolling to see more buttons
- Look in different sections of the UI
- DON'T click the same button repeatedly if nothing changes!

Recent actions that didn't help: {', '.join(state.action_history[-5:])}
"""
        
        system_prompt = """You are a web automation agent with WORKFLOW INTELLIGENCE. Your job is to:
1. Analyze the current UI state (navigation vs form/dialog)
2. Understand multi-step workflows specific to each platform
3. Execute actions in the correct sequence

🔄 WORKFLOW UNDERSTANDING:

📺 YOUTUBE WORKFLOWS:
- To PLAY a video: Search → Click actual VIDEO TITLE/THUMBNAIL on results → Video plays
- Search suggestions (buttons) just execute the search - they DON'T play videos!
- Look for links with role="link" containing video titles to actually open videos
- Success = URL contains "/watch?v=" (you're on the video page)
- ⚠️ IMPORTANT: Videos AUTO-PLAY when you navigate to them. If URL has /watch?v=, the video is ALREADY PLAYING!
- Once on /watch?v= page, DO NOT click play buttons - you're DONE!

📝 CREATE/ADD WORKFLOWS (Linear, GitHub, Jira, etc):
Creating/adding things typically follows this pattern:
1. Click a button to open a form/dialog (e.g., "Create new project")
2. Fill in ALL required input fields (name, description, etc.)
3. Click submit/save button to complete the action

⚠️ CRITICAL RULES:
- If you see "WORKFLOW DETECTION: FORM/DIALOG state" → You MUST fill inputs BEFORE clicking submit
- If inputs are marked "📝 INPUTS THAT NEED TO BE FILLED" → Fill them IMMEDIATELY
- NEVER click submit/create buttons without filling required fields first
- Always check if input fields exist before clicking submit buttons

ERROR HANDLING:
- If a name is taken, try a different one (add suffix, use timestamp)
- If an action fails 2-3 times, try a completely different approach
- Learn from errors and don't repeat the same failing action

🎯 SELECTOR SELECTION - CRITICALLY IMPORTANT:
You will be provided a list of "Available interactive elements" with their exact selectors.
YOU MUST ONLY USE SELECTORS FROM THIS LIST - DO NOT INVENT OR MODIFY THEM!

Rules for choosing selectors:
1. LOOK at the list of available elements carefully
2. CHOOSE the element that is most semantically relevant to your goal
3. COPY the selector EXACTLY as provided - character for character
4. DO NOT make up button names like "role=button[name='Rick Roll']" if it's not in the list
5. DO NOT assume what buttons should exist - only use what IS there
6. Use semantic understanding to map your goal to the CLOSEST matching element
7. "🎯 HIGHLY RELEVANT BUTTONS" are pre-scored - check these first, but verify the selector exists

Example:
- Goal: "play rick roll song"
- Available: button - "Rick Astley - Never Gonna Give You Up (Official Music Video)" (selector: role=link[name='...'])
- ✅ CORRECT: Use the selector for "Rick Astley - Never Gonna Give You Up" (it's the Rick Roll!)
- ❌ WRONG: Make up role=button[name='rick roll song'] - this doesn't exist!

ACTIONS:
- click: Click on an element (requires selector from the list)
- type: Type text into an input field (requires selector from the list and text)
- scroll: Scroll the page (optional delta in pixels)

Respond in JSON format:
{
  "reasoning": "Your analysis including which element you chose and WHY it matches semantically",
  "current_step": "What you're trying to accomplish right now",
  "action": {
    "type": "click|type|scroll",
    "selector": "EXACT selector copied from the list",
    "text": "text to type (if type action)",
    "delta": 700,
    "intent": "brief description of why"
  }
}"""

        user_prompt = f"""Goal: {state.goal}
Current URL: {state.current_url}
Step count: {state.step_count}/{state.max_steps}

Last action: {state.last_action or 'None'}
Last action result: {state.last_action_result or 'Unknown'}

Recent actions: {', '.join(state.action_history[-5:]) if state.action_history else 'None yet'}
{ui_context_text}{failure_warning}{loop_warning}
ERROR MESSAGES on page:
{errors_text}
{knowledge_hints}

Available interactive elements on the page:
{interactables_text if interactables_text else "No clear interactive elements found"}

What should I do next to achieve the goal?
REMEMBER THE WORKFLOW: If you're in a form, fill inputs FIRST, then submit!"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            
            # Parse JSON from response
            if isinstance(content, str):
                # Try to extract JSON from markdown code blocks if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                result = json.loads(content)
            else:
                result = content
            
            state.reasoning = result.get('reasoning', '')
            state.current_step = result.get('current_step', '')
            state.next_action = result.get('action', {})
            
            # ✅ VALIDATE: Check if the selector actually exists in the available interactables
            action_type = state.next_action.get('type', '')
            if action_type in ['click', 'type']:
                proposed_selector = state.next_action.get('selector', '')
                
                # Get list of valid selectors
                valid_selectors = [item.get('selector', '') for item in interactables]
                
                if proposed_selector and proposed_selector not in valid_selectors:
                    print(f"[WARNING] LLM hallucinated selector: {proposed_selector}")
                    print(f"[WARNING] This selector does not exist in available elements!")
                    print(f"[WARNING] Forcing LLM to reconsider from actual options...")
                    
                    # Find the closest match based on the intent/reasoning
                    intent = state.next_action.get('intent', '').lower()
                    reasoning = state.reasoning.lower()
                    
                    # Try to find a semantically similar element
                    best_match = None
                    best_score = 0
                    
                    for item in interactables:
                        label = item.get('label', '').lower()
                        role = item.get('role', '')
                        score = 0
                        
                        # Score based on overlap with intent and reasoning
                        for word in intent.split() + reasoning.split():
                            if len(word) > 3 and word in label:
                                score += 1
                        
                        if score > best_score:
                            best_score = score
                            best_match = item
                    
                    if best_match and best_score > 0:
                        print(f"[FIX] Using closest match: {best_match.get('label')} (selector: {best_match.get('selector')})")
                        state.next_action['selector'] = best_match.get('selector')
                        state.reasoning += f"\n[AUTO-CORRECTED: LLM proposed invalid selector, using closest match: {best_match.get('label')}]"
                    else:
                        # No good match found, just scroll to explore
                        print(f"[FIX] No close match found. Scrolling to explore more.")
                        state.next_action = {'type': 'scroll', 'delta': 700, 'intent': 'explore to find relevant elements'}
                        state.reasoning += "\n[AUTO-CORRECTED: Invalid selector, scrolling to explore]"
            
        except Exception as e:
            print(f"[ERROR] LLM planning failed: {e}")
            # Fallback: scroll
            state.reasoning = f"Error in LLM call: {e}"
            state.current_step = "Exploring page"
            state.next_action = {'type': 'scroll', 'delta': 700, 'intent': 'explore'}
        
        return state

    def validate_completion(self, state: AgentState) -> AgentState:
        """Use LLM to determine if the goal has been achieved."""
        obs = state.observation or {}
        hint = obs.get('hint', '')
        
        # 🎯 PRE-VALIDATION: Check for obvious success patterns before calling LLM
        goal_lower = state.goal.lower()
        current_url = state.current_url or ''
        
        # YouTube: If goal is to play/watch video and we're on /watch?v=, it's success!
        if any(word in goal_lower for word in ['youtube', 'play', 'watch']) and '/watch?v=' in current_url:
            state.done = True
            state.success = True
            print(f"[SUCCESS] Video is playing! URL: {current_url}")
            print(f"[SUCCESS] YouTube videos auto-play when navigated to - goal achieved!")
            return state
        
        system_prompt = """You are validating if a web automation goal has been completed.
Analyze the current state and determine if the goal has been successfully achieved.

⚠️ IMPORTANT VALIDATION RULES:
- For "play video" goals on YouTube: URL MUST contain "/watch?v=" to be on an actual video page
- For "search" goals: Being on search results page (/results?search_query=...) is SUCCESS
- For "create/add" goals: Check if the item was actually created (look for confirmation)
- Don't assume success just because an action was clicked - verify the RESULT

COMMON MISTAKES TO AVOID:
- YouTube: Clicking a search suggestion ≠ playing a video. Must be on /watch?v= page!
- Linear/Jira: Opening a dialog ≠ creating an item. Must fill form AND submit!
- GitHub: Clicking "New repo" ≠ creating repo. Must complete the form!

Respond in JSON format:
{
  "completed": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "Why you think it's complete or not, based on URL and actions",
  "success": true/false
}"""

        user_prompt = f"""Goal: {state.goal}
Current URL: {state.current_url}
Steps taken: {state.step_count}
Last action: {state.last_action}
Recent actions: {', '.join(state.action_history[-5:]) if state.action_history else 'None'}
Hint from page: {hint}

Has the goal been achieved? Is the task complete?

For reference:
- If goal involves "play video on YouTube", URL should be youtube.com/watch?v=... (not just search results)
- If goal involves "create/add", there should be confirmation of creation
- Check the URL pattern to verify we're on the right page type"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            content = response.content
            
            if isinstance(content, str):
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                result = json.loads(content)
            else:
                result = content
            
            if result.get('completed', False) and result.get('confidence', 0) > 0.7:
                state.done = True
                state.success = result.get('success', True)
                print(f"[SUCCESS] Goal achieved! Reasoning: {result.get('reasoning')}")
            
        except Exception as e:
            print(f"[ERROR] Validation failed: {e}")
        
        return state

