from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Dict, List, Optional
from datetime import datetime


class Interactable(BaseModel):
    model_config = ConfigDict(ser_json_timedelta='iso8601')
    
    role: str
    label: Optional[str] = None
    selector: Optional[str] = None


class CapturedState(BaseModel):
    model_config = ConfigDict(ser_json_timedelta='iso8601')
    
    id: str
    label: str
    url: Optional[str]
    dom_fingerprint: str
    visual_hash: str
    screenshot_path: str
    interactables: List[Interactable] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    action_leading_here: Optional[str] = None


class AgentMemory(BaseModel):
    model_config = ConfigDict(ser_json_timedelta='iso8601')
    
    seen_fingerprints: List[str] = []
    states: List[CapturedState] = []


class AgentState(BaseModel):
    model_config = ConfigDict(ser_json_timedelta='iso8601', arbitrary_types_allowed=True)
    
    # Core config
    app: str
    goal: str
    cookies_path: str
    dataset_dir: str
    working_dir: str
    
    # Current state
    current_url: Optional[str] = None
    observation: Dict[str, Any] = {}
    screenshot: Optional[bytes] = None
    
    # Reasoning & planning
    reasoning: Optional[str] = None  # LLM reasoning about current state
    plan: Optional[str] = None  # Step-by-step plan
    current_step: Optional[str] = None  # What we're trying to do now
    next_action: Optional[Dict[str, Any]] = None  # Planned action
    
    # History
    last_action: Optional[str] = None
    last_action_result: Optional[str] = None  # Result of last action (success/error)
    action_history: List[str] = []
    consecutive_failures: int = 0  # Track consecutive failed actions
    failed_action_type: Optional[str] = None  # Type of action that's failing
    same_url_action_count: int = 0  # Track actions on same URL (loop detection)
    last_url: Optional[str] = None  # Previous URL to detect loops
    step_count: int = 0
    max_steps: int = 50
    
    # Completion
    done: bool = False
    success: bool = False
    failure_reason: Optional[str] = None
    
    # Memory
    memory: AgentMemory = Field(default_factory=AgentMemory)

