"""Pydantic models for structured action definitions, inspired by browser-use's ActionModel."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class ClickAction(BaseModel):
    """Click action model."""
    action_type: Literal["click"] = "click"
    index: Optional[int] = Field(None, description="Element index from selector map")
    selector: str = Field(..., description="CSS selector or role selector")
    label: Optional[str] = Field(None, description="Element label for reference")


class TypeAction(BaseModel):
    """Type action model."""
    action_type: Literal["type"] = "type"
    index: Optional[int] = Field(None, description="Element index from selector map")
    selector: str = Field(..., description="CSS selector or role selector")
    text: str = Field(..., description="Text to type")
    label: Optional[str] = Field(None, description="Element label for reference")


class ScrollAction(BaseModel):
    """Scroll action model."""
    action_type: Literal["scroll"] = "scroll"
    direction: Literal["up", "down"] = Field("down", description="Scroll direction")
    pages: float = Field(1.0, description="Number of pages to scroll (0.5 = half page)")


class NavigateAction(BaseModel):
    """Navigate action model."""
    action_type: Literal["navigate"] = "navigate"
    url: str = Field(..., description="URL to navigate to")


# Union type for all actions
ActionModel = ClickAction | TypeAction | ScrollAction | NavigateAction


class ActionResult(BaseModel):
    """Result of executing an action, inspired by browser-use's ActionResult."""
    
    # Success/failure
    success: bool = Field(False, description="Whether action succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    # Content extraction
    extracted_content: Optional[str] = Field(
        None,
        description="Content extracted from page after action (e.g., form values, page text)"
    )
    long_term_memory: Optional[str] = Field(
        None,
        description="Important information to remember for future steps"
    )
    
    # Metadata
    metadata: Optional[dict] = Field(None, description="Additional metadata (coordinates, etc.)")
    
    # Task completion
    is_done: bool = Field(False, description="Whether task is complete")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for state updates."""
        return {
            'success': self.success,
            'error': self.error,
            'extracted_content': self.extracted_content,
            'long_term_memory': self.long_term_memory,
            'is_done': self.is_done,
        }

