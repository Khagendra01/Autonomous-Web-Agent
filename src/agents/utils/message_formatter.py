"""Enhanced message formatting for LLM communication, inspired by browser-use's AgentMessagePrompt."""
from typing import Dict, Any, List, Optional
from datetime import datetime
from ..utils.dom_enhanced import DOMSelectorMap, create_dom_summary


class AgentMessageFormatter:
    """Formats agent state into structured messages for LLM consumption.
    
    This class creates well-structured messages similar to browser-use's
    AgentMessagePrompt, with sections for different types of context.
    """
    
    def __init__(
        self,
        goal: str,
        instruction: str = "",
        current_url: str = "",
        step_count: int = 0,
        max_steps: int = 15,
    ):
        self.goal = goal
        self.instruction = instruction
        self.current_url = current_url
        self.step_count = step_count
        self.max_steps = max_steps
    
    def format_state_message(
        self,
        selector_map: DOMSelectorMap,
        action_history: List[Dict[str, Any]],
        errors: List[str] = None,
        screenshot_available: bool = False,
        goal_evaluation: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a comprehensive state message for the LLM.
        
        Format inspired by browser-use's message structure:
        - <agent_state>: Task, step info, available files
        - <agent_history>: Previous steps and results
        - <browser_state>: Current page state with interactive elements
        - <read_state>: Extracted content from previous actions (optional)
        """
        errors = errors or []
        
        # Build agent state section
        agent_state = self._build_agent_state()
        
        # Build agent history section
        agent_history = self._build_agent_history(action_history)
        
        # Build browser state section
        browser_state = self._build_browser_state(selector_map, errors)
        
        # Build read state section (from goal evaluation if available)
        read_state = ""
        if goal_evaluation:
            read_state = self._build_read_state(goal_evaluation)
        
        # Combine sections
        parts = [
            "<agent_state>",
            agent_state,
            "</agent_state>",
            "",
            "<agent_history>",
            agent_history,
            "</agent_history>",
            "",
            "<browser_state>",
            browser_state,
            "</browser_state>",
        ]
        
        if read_state:
            parts.extend([
                "",
                "<read_state>",
                read_state,
                "</read_state>",
            ])
        
        if screenshot_available:
            parts.append("\n[SCREENSHOT: Available for vision models]")
        
        return "\n".join(parts)
    
    def _build_agent_state(self) -> str:
        """Build the agent state section."""
        time_str = datetime.now().strftime('%Y-%m-%d')
        
        parts = [
            f"<user_request>",
            f"{self.instruction or self.goal}",
            f"</user_request>",
            "",
            f"<step_info>",
            f"Step {self.step_count + 1} of {self.max_steps}",
            f"Today: {time_str}",
            f"</step_info>",
        ]
        
        return "\n".join(parts)
    
    def _build_agent_history(self, action_history: List[Dict[str, Any]]) -> str:
        """Build the agent history section from previous actions."""
        if not action_history:
            return "No previous actions."
        
        parts = []
        # Show last 5-10 actions (most recent first for easier reading)
        recent = action_history[-10:]
        
        for i, action in enumerate(recent):
            step_num = len(action_history) - len(recent) + i + 1
            action_type = action.get('type', 'unknown')
            label = action.get('label', 'N/A')
            score = action.get('score', 0)
            
            text_part = ""
            if action_type == 'type' and action.get('text'):
                text_part = f" with text '{action['text']}'"
            
            parts.append(f"Step {step_num}: {action_type} on '{label}'{text_part} (score: {score:.1f})")
        
        if len(action_history) > len(recent):
            parts.insert(0, f"... {len(action_history) - len(recent)} previous steps ...")
        
        return "\n".join(parts) if parts else "No previous actions."
    
    def _build_browser_state(
        self,
        selector_map: DOMSelectorMap,
        errors: List[str],
    ) -> str:
        """Build the browser state section with page statistics and elements."""
        dom_summary = create_dom_summary(selector_map)
        stats = dom_summary['stats']
        elements_text = dom_summary['elements_text']
        
        parts = []
        
        # Page statistics
        stats_line = (
            f"{stats['links']} links, {stats['interactive_elements']} interactive, "
            f"{stats['buttons']} buttons, {stats['inputs']} inputs, "
            f"{stats['total_elements']} total elements"
        )
        parts.append(f"<page_stats>{stats_line}</page_stats>")
        parts.append("")
        parts.append(f"Current URL: {self.current_url}")
        parts.append("")
        
        # Errors if any
        if errors:
            parts.append(f"Errors: {', '.join(errors)}")
            parts.append("")
        
        # Interactive elements (the main content for LLM)
        parts.append("Interactive elements:")
        parts.append(elements_text)
        
        return "\n".join(parts)
    
    def _build_read_state(self, goal_evaluation: Dict[str, Any]) -> str:
        """Build the read state section from goal evaluation results."""
        parts = []
        
        if goal_evaluation.get('goal_reached'):
            parts.append("Goal Status: ✅ COMPLETED")
        else:
            parts.append("Goal Status: ⏳ IN PROGRESS")
        
        reasoning = goal_evaluation.get('reasoning', '')
        if reasoning:
            parts.append(f"Reasoning: {reasoning}")
        
        missing_steps = goal_evaluation.get('missing_steps', [])
        if missing_steps:
            parts.append("Missing steps:")
            for step in missing_steps:
                parts.append(f"  - {step}")
        
        return "\n".join(parts)


def format_action_scoring_prompt(
    goal: str,
    instruction: str,
    current_url: str,
    selector_map: DOMSelectorMap,
    action_history: List[Dict[str, Any]],
    errors: List[str] = None,
) -> str:
    """Format a prompt for LLM to score actions.
    
    This creates a more structured prompt compared to the original,
    giving the LLM better context and clearer instructions.
    """
    formatter = AgentMessageFormatter(goal, instruction, current_url)
    
    # Get summary info
    dom_summary = create_dom_summary(selector_map)
    stats = dom_summary['stats']
    elements_list = dom_summary['elements_list']
    
    errors = errors or []
    recent_history = action_history[-5:] if action_history else []
    
    prompt_parts = [
        "You are assisting an autonomous web agent. Score interactive elements by how likely they are to help achieve the goal.",
        "",
        "Context:",
        f"- Goal: {goal}",
        f"- Instruction: {instruction}",
        f"- Current URL: {current_url}",
        "",
        f"Page Statistics: {stats['interactive_elements']} interactive elements ({stats['buttons']} buttons, {stats['inputs']} inputs, {stats['links']} links)",
        "",
    ]
    
    if recent_history:
        prompt_parts.append("Recent Actions:")
        for action in recent_history:
            prompt_parts.append(f"  - {action.get('type', 'unknown')} on '{action.get('label', 'N/A')}'")
        prompt_parts.append("")
    
    if errors:
        prompt_parts.append(f"Errors/Validation: {', '.join(errors)}")
        prompt_parts.append("")
    
    prompt_parts.extend([
        "Available Interactive Elements:",
        f"(Showing top {len(elements_list)} elements)",
        "",
    ])
    
    # Add elements in JSON format for easier parsing
    import json
    prompt_parts.append(json.dumps(elements_list, indent=2))
    prompt_parts.append("")
    
    prompt_parts.extend([
        "Task: Return a JSON array of recommended actions with scores from 0-10.",
        "",
        "Scoring scale:",
        "- 10 = Directly achieves the goal or is the next critical step",
        "- 7-9 = Very likely to progress toward the goal",
        "- 4-6 = Possibly useful or indirectly related",
        "- 0-3 = Unlikely to help or wrong direction",
        "",
        "Principles:",
        "1) Disabled elements are not actionable → score 0-2",
        "2) Prefer elements whose labels/roles semantically match goal terms",
        "3) If goal requires data entry, prioritize relevant input fields",
        "4) If no strong candidates exist, include low-risk exploration (scroll/open menu)",
        "5) Avoid repeating recently ineffective actions",
        "6) If there are validation errors, prioritize actions that resolve them",
        "",
        "Return ONLY a JSON array:",
        '[{"action_type": "click|type|scroll", "selector": "...", "label": "...", "score": 0-10, "reasoning": "...", "text": "optional for type"}]',
    ])
    
    return "\n".join(prompt_parts)

