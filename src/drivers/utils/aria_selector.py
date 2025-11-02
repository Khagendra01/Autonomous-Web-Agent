"""ARIA selector handling for dropdowns, menus, and options.

This module provides utilities to find and interact with ARIA elements
like options, menuitems, and links, with robust fallback strategies.
"""

from __future__ import annotations
import re
from typing import Union
from playwright.sync_api import Locator, Frame, Page

from .selector_normalizer import normalize_label


def _get_context(ctx: Union[Page, Frame]) -> Union[Page, Frame]:
    """Get the page context from a frame or page."""
    if hasattr(ctx, 'page'):
        return ctx.page
    return ctx


def ensure_container_open(ctx: Union[Page, Frame], page: Page) -> None:
    """Ensure dropdown/menu containers are open before interacting.
    
    Attempts to open containers by clicking comboboxes or pressing keyboard shortcuts.
    
    Args:
        ctx: The context (Page or Frame) to operate in
        page: The main page object for wait operations
    """
    try:
        container = ctx.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first
        if container.count() == 0 or not container.is_visible():
            # Try clicking a closed combobox
            try:
                combo = ctx.locator('[role="combobox"]').filter(has=ctx.locator('[aria-expanded="false"]')).first
                if combo and (combo.count() > 0):
                    combo.click(timeout=800)
            except Exception:
                pass
            
            # Try keyboard shortcut
            try:
                keyboard = ctx.page.keyboard if hasattr(ctx, 'page') else ctx.keyboard
                keyboard.press('Alt+ArrowDown')
            except Exception:
                pass
            
            page.wait_for_timeout(200)
        
        # Wait for container to be visible
        ctx.locator('[role="listbox"], [role="menu"], [data-state="open"], [aria-modal="true"]').first.wait_for(state='visible', timeout=8000)
    except Exception:
        pass


def find_aria_element(
    ctx: Union[Page, Frame],
    role: str,
    label: str,
    page: Page | None = None,
    for_screenshot: bool = False
) -> Locator | None:
    """Find an ARIA element (option, menuitem, or link) by role and label.
    
    Uses multiple strategies to find the element:
    1. Direct role matching with normalized label
    2. Locator with has_text
    3. Case-insensitive regex matching
    4. Email extraction if email is in label
    5. Partial word matching
    
    Args:
        ctx: The context (Page or Frame) to search in
        role: ARIA role ('option', 'menuitem', or 'link')
        label: The label text to match
        page: Optional page object for wait operations
        for_screenshot: If True, returns first candidate without trying all strategies
    
    Returns:
        A Locator for the element, or None if not found.
    """
    if not label or not role:
        return None
    
    normalized_label = normalize_label(label)
    original_label = label.strip() if label else ''
    
    # Try both normalized and original label if they're different
    labels_to_try = [normalized_label]
    if original_label and original_label != normalized_label:
        labels_to_try.append(original_label)
    
    # Build candidate list based on role
    candidates = []
    
    # Try each label variation
    for try_label in labels_to_try:
        if role == 'option':
            candidates.extend([
                ctx.get_by_role('option', name=try_label).first,
                ctx.locator('[role="option"]', has_text=try_label).first,
            ])
        elif role == 'menuitem':
            candidates.extend([
                ctx.get_by_role('menuitem', name=try_label).first,
                ctx.locator('[role="menuitem"]', has_text=try_label).first,
            ])
        elif role == 'link':
            candidates.extend([
                ctx.get_by_role('link', name=try_label).first,
                ctx.locator('[role="link"]', has_text=try_label).first,
                ctx.locator('a', has_text=try_label).first,
            ])
    
    # Add regex-based candidates - try both labels
    for try_label in labels_to_try:
        try:
            regex = re.compile(re.escape(try_label), re.IGNORECASE)
            if role == 'option':
                candidates.extend([
                    ctx.locator('[role="option"]').filter(has_text=regex).first,
                ])
            elif role == 'menuitem':
                candidates.extend([
                    ctx.locator('[role="menuitem"]').filter(has_text=regex).first,
                ])
            elif role == 'link':
                candidates.extend([
                    ctx.locator('[role="link"]').filter(has_text=regex).first,
                    ctx.locator('a').filter(has_text=regex).first,
                ])
        except Exception:
            pass
    
    # Extract email if present
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', normalized_label)
    if email_match:
        email_only = email_match.group(0)
        try:
            if role == 'option':
                candidates.extend([
                    ctx.locator('[role="option"]').filter(has_text=email_only).first,
                ])
            elif role == 'menuitem':
                candidates.extend([
                    ctx.locator('[role="menuitem"]').filter(has_text=email_only).first,
                ])
            elif role == 'link':
                candidates.extend([
                    ctx.locator('[role="link"]').filter(has_text=email_only).first,
                    ctx.locator('a').filter(has_text=email_only).first,
                ])
        except Exception:
            pass
    
    # Partial matching for multi-word labels
    if not for_screenshot:
        label_parts = normalized_label.split()
        if len(label_parts) > 1:
            for part in label_parts:
                if len(part) > 3:  # Only use meaningful parts
                    try:
                        if role == 'option':
                            candidates.extend([
                                ctx.locator('[role="option"]').filter(has_text=part).first,
                            ])
                        elif role == 'menuitem':
                            candidates.extend([
                                ctx.locator('[role="menuitem"]').filter(has_text=part).first,
                            ])
                        elif role == 'link':
                            candidates.extend([
                                ctx.locator('[role="link"]').filter(has_text=part).first,
                                ctx.locator('a').filter(has_text=part).first,
                            ])
                    except Exception:
                        pass
    
    # Try candidates
    for cand in candidates:
        try:
            if cand and cand.count() > 0:
                if for_screenshot:
                    cand.wait_for(state='visible', timeout=1000)
                    return cand
                else:
                    return cand
        except Exception:
            continue
    
    return None


def click_aria_element(
    ctx: Union[Page, Frame],
    role: str,
    label: str,
    page: Page,
    debug: bool = False
) -> bool:
    """Click an ARIA element (option, menuitem, or link) by role and label.
    
    Uses find_aria_element with additional fallback strategies and ensures
    the element is scrolled into view and clicked.
    
    Args:
        ctx: The context (Page or Frame) to operate in
        role: ARIA role ('option', 'menuitem', or 'link')
        label: The label text to match
        page: The main page object for wait operations
        debug: If True, print debug messages
    
    Returns:
        True if successfully clicked, False otherwise.
    """
    # Ensure container is open (for dropdowns/menus)
    if role in ('option', 'menuitem'):
        ensure_container_open(ctx, page)
    
    normalized_label = normalize_label(label)
    original_label = label.strip() if label else ''
    
    # Try both normalized and original label if they're different
    # This handles cases where DOM has duplicated labels like "email email" 
    # but we normalized to "email", or vice versa
    labels_to_try = [normalized_label]
    if original_label and original_label != normalized_label:
        labels_to_try.append(original_label)
    
    if debug:
        print(f"    [DEBUG] Trying labels: {labels_to_try} (original: '{original_label}', normalized: '{normalized_label}')")
    
    # Build comprehensive candidate list (same as find_aria_element but with all strategies)
    candidates = []
    
    # Try each label variation
    for try_label in labels_to_try:
        if role == 'option':
            candidates.extend([
                ctx.get_by_role('option', name=try_label).first,
                ctx.locator('[role="option"]', has_text=try_label).first,
            ])
        elif role == 'menuitem':
            candidates.extend([
                ctx.get_by_role('menuitem', name=try_label).first,
                ctx.locator('[role="menuitem"]', has_text=try_label).first,
            ])
        elif role == 'link':
            candidates.extend([
                ctx.get_by_role('link', name=try_label).first,
                ctx.locator('[role="link"]', has_text=try_label).first,
                ctx.locator('a', has_text=try_label).first,
            ])
    
    # Regex candidates - try both labels
    for try_label in labels_to_try:
        try:
            regex = re.compile(re.escape(try_label), re.IGNORECASE)
            if role == 'option':
                candidates.extend([
                    ctx.locator('[role="option"]').filter(has_text=regex).first,
                ])
            elif role == 'menuitem':
                candidates.extend([
                    ctx.locator('[role="menuitem"]').filter(has_text=regex).first,
                ])
            elif role == 'link':
                candidates.extend([
                    ctx.locator('[role="link"]').filter(has_text=regex).first,
                    ctx.locator('a').filter(has_text=regex).first,
                ])
        except Exception:
            pass
    
    # Email extraction - try from both labels
    for try_label in labels_to_try:
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', try_label)
        if email_match:
            email_only = email_match.group(0)
            try:
                if role == 'option':
                    candidates.extend([
                        ctx.locator('[role="option"]').filter(has_text=email_only).first,
                    ])
                elif role == 'menuitem':
                    candidates.extend([
                        ctx.locator('[role="menuitem"]').filter(has_text=email_only).first,
                    ])
                elif role == 'link':
                    candidates.extend([
                        ctx.locator('[role="link"]').filter(has_text=email_only).first,
                        ctx.locator('a').filter(has_text=email_only).first,
                    ])
            except Exception:
                pass
            break  # Email is same in both labels, no need to try twice
    
    # Partial matching - use normalized label (already deduplicated)
    label_parts = normalized_label.split()
    if len(label_parts) > 1:
        for part in label_parts:
            if len(part) > 3:
                try:
                    if role == 'option':
                        candidates.extend([
                            ctx.locator('[role="option"]').filter(has_text=part).first,
                        ])
                    elif role == 'menuitem':
                        candidates.extend([
                            ctx.locator('[role="menuitem"]').filter(has_text=part).first,
                        ])
                    elif role == 'link':
                        candidates.extend([
                            ctx.locator('[role="link"]').filter(has_text=part).first,
                            ctx.locator('a').filter(has_text=part).first,
                        ])
                except Exception:
                    pass
    
    # Try clicking candidates
    for cand in candidates:
        try:
            if cand and cand.count() > 0:
                try:
                    cand.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                cand.wait_for(state='visible', timeout=8000)
                
                # For dropdown options/menuitems, interception is common - try force/JS click first
                # For links, try normal click first
                if role in ('option', 'menuitem'):
                    # Dropdown options often have scrollable containers that intercept clicks
                    # Try JavaScript click first (fastest, bypasses all actionability)
                    try:
                        if debug:
                            print(f"    [DEBUG] Trying JavaScript click first (role={role})...")
                        cand.evaluate('element => element.click()')
                        page.wait_for_timeout(200)
                        return True
                    except Exception as js_err:
                        if debug:
                            print(f"    [DEBUG] JavaScript click failed, trying force click: {js_err}")
                        try:
                            # Try force click (bypasses actionability but still uses native click)
                            cand.click(timeout=3000, force=True)
                            page.wait_for_timeout(200)
                            return True
                        except Exception as force_err:
                            if debug:
                                print(f"    [DEBUG] Force click failed, trying normal click: {force_err}")
                            # Last resort: normal click with short timeout
                            try:
                                cand.click(timeout=3000)
                                page.wait_for_timeout(200)
                                return True
                            except Exception:
                                pass
                else:
                    # For links, try normal click first
                    try:
                        cand.click(timeout=5000)
                        page.wait_for_timeout(200)
                        return True
                    except Exception as click_err:
                        error_str = str(click_err).lower()
                        # Check if click was blocked by intercepting element
                        if 'intercept' in error_str or 'pointer' in error_str:
                            if debug:
                                print(f"    [DEBUG] Normal click blocked, trying force click...")
                            try:
                                # Try force click (bypasses actionability checks)
                                cand.click(timeout=3000, force=True)
                                page.wait_for_timeout(200)
                                return True
                            except Exception as force_err:
                                if debug:
                                    print(f"    [DEBUG] Force click failed, trying JS click: {force_err}")
                                try:
                                    # Try JavaScript click as fallback
                                    cand.evaluate('element => element.click()')
                                    page.wait_for_timeout(200)
                                    return True
                                except Exception as js_err:
                                    if debug:
                                        print(f"    [DEBUG] JavaScript click failed: {js_err}")
                        else:
                            # Different error, continue to next candidate
                            if debug:
                                print(f"    [DEBUG] Click failed with different error: {click_err}")
                            pass
        except Exception as e:
            if debug:
                print(f"    [DEBUG] Candidate failed: {e}")
            continue
    
    # Last resort: if only one option/menuitem/link is visible, click it
    if role in ('option', 'menuitem'):
        try:
            all_options = ctx.locator('[role="option"]:visible, [role="menuitem"]:visible, [role="listbox"] a:visible')
            if all_options.count() == 1:
                last_resort = all_options.first
                try:
                    last_resort.click(timeout=5000)
                    page.wait_for_timeout(200)
                    return True
                except Exception as click_err:
                    error_str = str(click_err).lower()
                    if 'intercept' in error_str or 'pointer' in error_str:
                        # Try force click or JavaScript click
                        try:
                            last_resort.click(timeout=5000, force=True)
                            page.wait_for_timeout(200)
                            return True
                        except Exception:
                            try:
                                last_resort.evaluate('element => element.click()')
                                page.wait_for_timeout(200)
                                return True
                            except Exception:
                                pass
        except Exception:
            pass
    
    return False

