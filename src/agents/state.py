from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from datetime import datetime


class Interactable(BaseModel):
    role: str
    label: Optional[str] = None
    selector: Optional[str] = None


class CapturedState(BaseModel):
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
    seen_fingerprints: List[str] = []
    states: List[CapturedState] = []


class AgentState(BaseModel):
    app: str
    goal: str
    cookies_path: str
    dataset_dir: str
    working_dir: str
    current_url: Optional[str] = None
    last_action: Optional[str] = None
    observation: Dict[str, Any] = {}
    done: bool = False
    success: bool = False
    memory: AgentMemory = Field(default_factory=AgentMemory)

