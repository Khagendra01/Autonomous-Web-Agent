"""Trap element detection for rich text editors.

This module provides utilities to detect and filter out "trap" elements created
by rich text editors (like TinyMCE, CKEditor, etc.) that appear in the accessibility
tree but should not be directly interacted with.
"""

from __future__ import annotations
from playwright.sync_api import Page


def is_trap_element(page_ref: Page | None, element_name: str = '') -> bool:
    """Check if a textbox element is a trap element from rich text editors.
    
    Trap elements are helper DOM nodes created by rich text editors (like TinyMCE, CKEditor, etc.)
    that appear in the accessibility tree but should not be directly interacted with.
    
    Args:
        page_ref: Playwright Page object, or None if unavailable
        element_name: Optional name/label of the element to check. If provided, only
                     elements matching this name will be checked.
    
    Returns:
        True if the element is a trap, False otherwise.
    """
    if not page_ref:
        return False
    try:
        # More robust trap detection: check for multiple editor patterns
        is_trap = page_ref.evaluate(
            """
            (name) => {
              try {
                const matches = document.querySelectorAll('*[role="textbox"]');
                for (const el of matches) {
                  // Match by name if provided
                  if (name) {
                    const ariaLabel = el.getAttribute('aria-label') || el.textContent || '';
                    if (ariaLabel.trim() !== name) continue;
                  }
                  
                  // TinyMCE trap pattern
                  if (el.hasAttribute('data-content-editable-root-tiny-selection-trap')) return true;
                  if (el.closest('[data-content-editable-root-tiny-selection-trap]')) return true;
                  
                  // Other common trap patterns:
                  // - Elements with contenteditable="false" inside contenteditable containers
                  if (el.hasAttribute('contenteditable') && el.getAttribute('contenteditable') === 'false') {
                    const parent = el.parentElement;
                    if (parent && parent.hasAttribute('contenteditable') && parent.getAttribute('contenteditable') === 'true') {
                      return true;
                    }
                  }
                  
                  // - Hidden/zero-sized trap divs with role="textbox"
                  const style = window.getComputedStyle(el);
                  const rect = el.getBoundingClientRect();
                  if (style.display === 'none' || style.visibility === 'hidden' || 
                      rect.width === 0 || rect.height === 0) {
                    // Only consider it a trap if it's clearly a helper element
                    const classes = Array.from(el.classList || []);
                    const hasEditorClass = classes.some(c => 
                      c.includes('editor') || c.includes('trap') || c.includes('helper') || 
                      c.includes('tinymce') || c.includes('ckeditor')
                    );
                    if (hasEditorClass) return true;
                  }
                }
                return false;
              } catch (e) { return false; }
            }
            """,
            element_name
        )
        return bool(is_trap)
    except Exception:
        return False

