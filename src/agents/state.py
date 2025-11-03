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
    prev_interactable_count: int
    errors: List[str]
    active_context: Optional[Dict[str, Any]]
    
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
    
    # Anti-loop memory
    # Map of URL -> list of action keys that were already tried on that view
    tried_actions_by_url: Dict[str, List[str]]
    
    # Temporal tracking for element detection
    prev_interactable_elements: Optional[List[Dict[str, Any]]]  # Elements from previous observation
    
    # Sub-task tracking (for multi-step goals)
    sub_tasks: Optional[List[Dict[str, Any]]]  # Parsed sub-tasks with completion tracking
    current_sub_task_index: int  # Which sub-task we're currently working on

    # Declarative requirements and gating
    # Generic requirement predicates normalized by upstream nodes (e.g., parser/bootstrap/evaluator)
    # Examples: { "titleSet": true, "assigneeSet": true, "projectSet": true }
    requirements: Dict[str, bool]
    # Deterministic predicate truths observed from the DOM (persisted UI state)
    predicate_truths: Dict[str, bool]
    # Internal locks / cadence controls
    execution_step_lock: Optional[int]  # Prevent duplicate execute within same step
    last_evaluated_step: Optional[int]  # Prevent duplicate evaluate within same step

    # Target entity anchoring (object permanence across steps)
    # Example for issues: { "id": "ALP-7", "title": "Clean up the UI", "url": "/issue/ALP-7/..." }
    target_entity: Optional[Dict[str, Any]]

