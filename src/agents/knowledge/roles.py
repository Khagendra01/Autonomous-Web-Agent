"""Centralized knowledge about actionable roles and click fallbacks.

Keep these lists small, conservative, and app-agnostic. Expand incrementally.
"""

# Roles that usually represent direct user actions
ACTIONABLE_ROLES: set[str] = {
    # Primary action controls
    'button', 'link', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    # Selection/choice items
    'option', 'treeitem', 'tab',
    # Binary controls
    'checkbox', 'radio', 'switch',
    # Inputs
    'textbox', 'searchbox', 'combobox', 'spinbutton',
    # Range controls
    'slider',
    # Often interactive table items
    'gridcell', 'rowheader', 'columnheader',
}

# Container roles that are not typically clicked directly (children are)
NON_ACTION_CONTAINER_ROLES: set[str] = {
    'listbox', 'menu', 'menubar', 'tablist', 'dialog', 'grid', 'table',
}

# Generic HTML fallbacks when role is missing/misused
# These are hints only; still require visibility/size/pointer-events checks upstream
CLICKABLE_FALLBACK_TAGS: set[str] = {
    'a', 'button', 'summary',
}


