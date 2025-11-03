"""Utilities for the Playwright driver server.

This package contains helper modules for:
- Trap element detection (rich text editor helpers)
- Selector normalization (keyboard hint removal)
- ARIA selector handling (dropdowns, menus, options)
"""

from .trap_finder import is_trap_element
from .selector_normalizer import normalize_label
from .aria_selector import find_aria_element, click_aria_element

__all__ = [
    'is_trap_element',
    'normalize_label',
    'find_aria_element',
    'click_aria_element',
]

