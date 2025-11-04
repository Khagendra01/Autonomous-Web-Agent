"""Improved selector generation that prefers stable, shorter selectors."""
from __future__ import annotations
import re
from typing import Optional


def generate_best_selector(
    role: str,
    label: str,
    tag: str = '',
    elem_id: str = '',
    href: str = '',
    classes: list[str] | None = None,
    elem_type: str = '',
    placeholder: str = '',
) -> str:
    """
    Generate the best possible selector, preferring stable and shorter options.
    
    Priority order:
    1. ID selector (most stable)
    2. href for links (very stable)
    3. Short, meaningful text match (first 3-4 words)
    4. Role + partial name match (shorter text)
    5. Role + full name (fallback)
    
    Args:
        role: ARIA role
        label: Full accessible name/label
        tag: HTML tag name
        elem_id: Element ID
        href: Link href attribute
        classes: CSS classes
        elem_type: Input type
        placeholder: Placeholder text
        
    Returns:
        Best selector string
    """
    # Priority 1: ID selector (most stable)
    if elem_id and elem_id.strip():
        # Validate ID is safe for CSS selector
        safe_id = elem_id.strip()
        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', safe_id):
            return f'#{safe_id}'
        # For IDs with special chars, use attribute selector
        return f'[id="{safe_id}"]'
    
    # Priority 2: href for links (very stable)
    if role == 'link' and href and href.strip():
        # Use href as selector for links
        safe_href = href.strip()
        # Escape quotes
        safe_href = safe_href.replace('"', '\\"')
        return f'a[href="{safe_href}"]'
    
    # Priority 3: Short text match (first meaningful words)
    if label and label.strip():
        # Extract first 3-4 meaningful words (avoid very long labels)
        words = label.strip().split()
        if len(words) > 10:
            # For very long labels, use first few words plus last word (project name)
            # This handles cases like "Select project Choose icon Softlight No updates..."
            short_label = ' '.join(words[:2] + words[-2:])  # First 2 + last 2 words
        elif len(words) > 4:
            # For medium labels, use first 3-4 words
            short_label = ' '.join(words[:4])
        else:
            # Short labels are fine as-is
            short_label = label.strip()
        
        # Clean up the label
        short_label = re.sub(r'\s+', ' ', short_label).strip()
        
        # Limit length to avoid selector issues
        if len(short_label) > 60:
            short_label = short_label[:60]
        
        # Escape quotes
        safe_label = short_label.replace('"', '\\"')
        
        # Use role + shorter name
        return f'role={role}[name*="{safe_label}"]'  # Partial match with *
    
    # Priority 4: Type-based for inputs
    if role == 'textbox' and elem_type:
        if placeholder:
            safe_placeholder = placeholder.replace('"', '\\"')
            return f'input[type="{elem_type}"][placeholder*="{safe_placeholder}"]'
        return f'input[type="{elem_type}"]'
    
    # Priority 5: Fallback to full role + name (but with escaping)
    if label and label.strip():
        safe_label = label.strip().replace('"', '\\"')
        # Limit to 100 chars to avoid issues
        if len(safe_label) > 100:
            safe_label = safe_label[:100]
        return f'role={role}[name="{safe_label}"]'
    
    # Last resort: role only
    return f'role={role}'


def extract_short_label(long_label: str, max_words: int = 4) -> str:
    """
    Extract a short, meaningful label from a long accessible name.
    
    Handles cases like:
    "Select project Choose icon Softlight No updates. Click to write update..."
    -> "Softlight" (prefers meaningful words, removes metadata)
    
    Args:
        long_label: Full accessible name
        max_words: Maximum words to include
        
    Returns:
        Shortened label
    """
    if not long_label or not long_label.strip():
        return ''
    
    words = long_label.strip().split()
    
    # First, try to find capitalized words (project names like "Softlight", "Happy", "beta")
    capitalized_words = [w for w in words if w and w[0].isupper() and len(w) > 2]
    if capitalized_words:
        # Prefer the first capitalized word that's not a common word
        common_words = {'Select', 'Choose', 'Click', 'No', 'Change', 'Project', 'Target', 'Date'}
        for cap_word in capitalized_words:
            if cap_word not in common_words:
                return cap_word  # Return just the project name
    
    # Also check for lowercase but meaningful words (like "beta")
    lowercase_meaningful = [w for w in words if w and w[0].islower() and len(w) > 3 and w.isalnum()]
    if lowercase_meaningful:
        # Check if it's not a metadata word
        metadata_lower = ['updates', 'priority', 'click', 'write', 'change', 'target', 'date']
        for word in lowercase_meaningful:
            if word.lower() not in metadata_lower:
                return word
    
    # Remove common metadata phrases
    metadata_patterns = [
        r'click\s+to\s+\w+',
        r'no\s+updates?',
        r'change\s+\w+',
        r'select\s+\w+',
        r'choose\s+icon',
        r'\d+%',  # Percentages
    ]
    
    filtered_words = []
    for word in words:
        word_lower = word.lower()
        is_metadata = any(re.search(pattern, word_lower) for pattern in metadata_patterns)
        if not is_metadata and len(word.strip()) > 0:
            filtered_words.append(word)
    
    # If we filtered out metadata, use remaining words
    if filtered_words:
        # Prefer the middle/end words (often the actual content)
        # Skip first 1-2 words if they're common verbs
        start_idx = 0
        if len(filtered_words) > 2:
            first_word_lower = filtered_words[0].lower()
            if first_word_lower in ['select', 'choose', 'click', 'show', 'add']:
                start_idx = 1
        
        short = ' '.join(filtered_words[start_idx:start_idx + max_words])
        if short:
            return short
    
    # Fallback: use first max_words
    return ' '.join(words[:max_words]) if words else ''

