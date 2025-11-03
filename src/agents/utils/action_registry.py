"""
Action registry with parameter validation following browser-use best practices.
"""
from typing import Dict, Any
from enum import Enum


class ActionType(str, Enum):
    """Supported action types."""
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    NAVIGATE = "navigate"
    SEQUENCE = "sequence"
    AWAIT = "await"
    ASSERT = "assert"
    PRESS = "press"


def validate_action_params(action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate action parameters based on action type.
    Returns validated params dict or raises ValueError.
    """
    validated = {}
    
    if action_type == ActionType.CLICK:
        if 'selector' not in params or not params['selector']:
            raise ValueError("Click action requires 'selector' parameter")
        validated['selector'] = str(params['selector'])
        # Optional params
        if 'frame' in params:
            validated['frame'] = int(params['frame'])
        if 'timeout' in params:
            validated['timeout'] = int(params['timeout'])
    
    elif action_type == ActionType.TYPE:
        if 'selector' not in params or not params['selector']:
            raise ValueError("Type action requires 'selector' parameter")
        if 'text' not in params or not params['text']:
            raise ValueError("Type action requires 'text' parameter")
        validated['selector'] = str(params['selector'])
        validated['text'] = str(params['text'])
        if 'timeout' in params:
            validated['timeout'] = int(params['timeout'])
    
    elif action_type == ActionType.SCROLL:
        if 'delta' not in params:
            raise ValueError("Scroll action requires 'delta' parameter")
        validated['delta'] = int(params['delta'])
    
    elif action_type == ActionType.NAVIGATE:
        if 'url' not in params or not params['url']:
            raise ValueError("Navigate action requires 'url' parameter")
        validated['url'] = str(params['url'])
    
    elif action_type == ActionType.SEQUENCE:
        if 'selectors' not in params or not params['selectors']:
            raise ValueError("Sequence action requires 'selectors' parameter (list)")
        validated['selectors'] = list(params['selectors'])
        if 'timeout' in params:
            validated['timeout'] = int(params['timeout'])
    
    elif action_type == ActionType.AWAIT:
        if 'kind' not in params:
            raise ValueError("Await action requires 'kind' parameter")
        validated['kind'] = str(params['kind'])
        if 'timeout' in params:
            validated['timeout'] = int(params['timeout'])
    
    elif action_type == ActionType.ASSERT:
        if 'kind' not in params:
            raise ValueError("Assert action requires 'kind' parameter")
        validated['kind'] = str(params['kind'])
        if 'text' in params:
            validated['text'] = str(params['text'])
        if 'selector' in params:
            validated['selector'] = str(params['selector'])
    
    elif action_type == ActionType.PRESS:
        if 'keys' not in params or not params['keys']:
            raise ValueError("Press action requires 'keys' parameter")
        validated['keys'] = str(params['keys'])
        if 'selector' in params:
            validated['selector'] = str(params['selector'])
    
    else:
        raise ValueError(f"Unknown action type: {action_type}")
    
    return validated


def get_action_description(action_type: str) -> str:
    """Get human-readable description for an action type."""
    descriptions = {
        ActionType.CLICK: "Click on an element",
        ActionType.TYPE: "Type text into an input field",
        ActionType.SCROLL: "Scroll the page up or down",
        ActionType.NAVIGATE: "Navigate to a URL",
        ActionType.SEQUENCE: "Execute a sequence of actions",
        ActionType.AWAIT: "Wait for a condition or timeout",
        ActionType.ASSERT: "Assert a condition is true",
        ActionType.PRESS: "Press keyboard keys",
    }
    return descriptions.get(action_type, f"Execute {action_type} action")

