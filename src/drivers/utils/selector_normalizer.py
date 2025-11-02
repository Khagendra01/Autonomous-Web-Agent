"""Selector and label normalization utilities.

This module provides functions to normalize labels by removing keyboard hints
and other accessibility annotations that can interfere with element matching.
"""

from __future__ import annotations
import re


def normalize_label(label: str, remove_keyboard_hints: bool = True) -> str:
    """Normalize a label by removing keyboard hints and extra whitespace.
    
    Removes patterns like "G then S" or "GthenS" that are keyboard shortcuts
    added to menu items and options in accessibility trees.
    
    Args:
        label: The label text to normalize
        remove_keyboard_hints: If True, remove keyboard hint patterns (e.g., "G then S")
    
    Returns:
        Normalized label with keyboard hints removed and whitespace cleaned.
    
    Examples:
        >>> normalize_label("Go then Search")
        "Go Search"
        >>> normalize_label("File  GthenS")
        "File"
        >>> normalize_label("Save")
        "Save"
    """
    if not label:
        return ''
    
    result = label
    
    if remove_keyboard_hints:
        try:
            # Remove patterns like "G then S" or "GthenS"
            result = re.sub(r'(?i)\b([A-Z])\s*then\s*([A-Z])\b', '', result)
            result = re.sub(r'(?i)\b[A-Z]then[A-Z]\b', '', result)
        except Exception:
            pass
    
    # Normalize whitespace (multiple spaces to single space)
    try:
        result = re.sub(r'\s{2,}', ' ', result)
        result = result.strip()
    except Exception:
        pass
    
    return result


def extract_label_from_selector(selector: str) -> str | None:
    """Extract the label from a role-based selector.
    
    Args:
        selector: Selector string like 'role=button[name="Save"]'
    
    Returns:
        The extracted label, or None if not found.
    
    Examples:
        >>> extract_label_from_selector('role=button[name="Save"]')
        "Save"
        >>> extract_label_from_selector('role=option[name="Go then Search"]')
        "Go then Search"
    """
    if not isinstance(selector, str):
        return None
    
    m = re.search(r'\[name="(.+?)"\]', selector)
    if m:
        return m.group(1)
    
    return None

