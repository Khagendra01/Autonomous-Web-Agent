"""Shared JSON extraction utilities for LLM response parsing."""
from typing import Any, Dict, List, Optional
import json
import re


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from text, handling code fences and fallback parsing.
    
    Args:
        text: Text that may contain a JSON object (possibly in code fences)
        
    Returns:
        Parsed JSON object as dict, or None if parsing fails
    """
    # Remove code fences if present
    if "```" in text:
        parts = text.split("```")
        # Prefer the first fenced block content
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()

    # Try direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Fallback: find the first top-level JSON object via regex
    try:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group(0))
    except Exception:
        return None
    return None


def extract_json_array(text: str) -> Optional[List[Any]]:
    """Extract a JSON array from text, handling code fences and fallback parsing.
    
    Args:
        text: Text that may contain a JSON array (possibly in code fences)
        
    Returns:
        Parsed JSON array as list, or None if parsing fails
    """
    # Strip fences
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.lstrip()[4:]
            text = candidate.strip()
    
    # Direct parse
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    
    # Regex fallback: find first bracketed array
    try:
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            obj = json.loads(match.group(0))
            if isinstance(obj, list):
                return obj
    except Exception:
        return None
    return None

