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
    Also handles duplicated text patterns (e.g., "email email" → "email").
    
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
        >>> normalize_label("kgen4295@gmail.com kgen4295@gmail.com")
        "kgen4295@gmail.com"
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
    
    # Handle duplicated text patterns (common in accessibility trees)
    # Pattern: "text text" or "kgen4295@gmail.com kgen4295@gmail.com" → "text" or "kgen4295@gmail.com"
    try:
        # Split into words/tokens
        parts = result.split()
        if len(parts) > 1:
            # Check if first half exactly matches second half (most common duplication pattern)
            mid_point = len(parts) // 2
            first_half = parts[:mid_point]
            second_half = parts[mid_point:]
            
            if first_half == second_half:
                # Remove duplication: "email email" → "email"
                result = ' '.join(first_half)
            elif len(parts) == 2 and parts[0] == parts[1]:
                # Simple case: two identical words
                result = parts[0]
            elif len(set(parts)) == 1:
                # All parts are identical (e.g., "word word word")
                result = parts[0]
    except Exception:
        pass
    
    return result


def is_placeholder_text(label: str) -> bool:
    """Detect if a label is placeholder/example text that shouldn't be interacted with.
    
    Common patterns:
    - "name@gmail.com" (generic email placeholder)
    - "example@..." (example email)
    - "email@example.com" (generic email format)
    - Labels with ellipsis "..." indicating placeholder
    
    Args:
        label: The label text to check
    
    Returns:
        True if the label appears to be placeholder/example text
    """
    if not label:
        return False
    
    label_lower = label.lower().strip()
    
    # Common placeholder patterns
    placeholder_patterns = [
        r'^name@.*\.com.*$',  # name@gmail.com, name@gmail.com, …
        r'^example@.*$',  # example@email.com
        r'^email@.*\.com.*$',  # email@example.com
        r'^.*@.*\.com.*,.*@.*\.com',  # Multiple email pattern
        r'^.*@.*\.com.*\.\.\.?$',  # Email with ellipsis
    ]
    
    for pattern in placeholder_patterns:
        if re.match(pattern, label_lower):
            return True
    
    # Check for generic words combined with email pattern
    generic_words = ['name', 'example', 'sample', 'demo', 'test', 'placeholder']
    if '@' in label_lower:
        # If it contains an email pattern and generic words, likely placeholder
        if any(word in label_lower for word in generic_words):
            return True
    
    # Check for ellipsis patterns (often indicate truncated/placeholder)
    if '…' in label or (label.count(',') > 1 and '@' in label):
        return True
    
    return False


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

