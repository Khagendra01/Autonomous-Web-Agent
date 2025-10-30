"""State definition for the autonomous web agent."""
from typing import TypedDict, List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class ScoredAction:
    """An action with its LLM-assigned score."""
    action_type: str  # 'click', 'type', 'scroll'
    selector: str
    label: str
    score: float  # 0-10, higher = more likely to reach goal
    reasoning: str
    text: Optional[str] = None  # for 'type' actions


class AgentState(TypedDict):
    """The state passed between nodes in the LangGraph."""
    # Instruction/task info
    instruction: str  # Natural language instruction from user
    goal: str  # Parsed/normalized goal (defaults to instruction)
    app_name: str
    base_url: str
    max_steps: int
    
    # Current state
    step_count: int
    current_url: str
    screenshot_bytes: Optional[bytes]
    dom_snapshot: Optional[Dict[str, Any]]
    interactable_elements: List[Dict[str, Any]]
    
    # History
    action_history: List[Dict[str, Any]]
    screenshots: List[bytes]
    
    # LLM scoring
    scored_actions: List[ScoredAction]
    next_action: Optional[ScoredAction]
    
    # Status
    goal_reached: bool
    error: Optional[str]
    stuck_count: int  # Track if we're repeating actions

