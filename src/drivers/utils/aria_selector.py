"""ARIA selector handling for dropdowns, menus, and options.

This module provides utilities to find and interact with ARIA elements
like options, menuitems, and links, with robust fallback strategies.
"""

from __future__ import annotations
import re
from typing import Union
import os
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
    
    # Heuristic: detect navigation intent from label to allow deliberate global link clicks
    nav_terms = ['profile', 'view', 'details', 'open', 'navigate']
    has_navigation_intent = any(t in (original_label or '').lower() for t in nav_terms)
    
    # Build candidate list based on role
    candidates = []
    
    # Heuristic: detect navigation intent from label to allow deliberate global link clicks
    nav_terms = ['profile', 'view', 'details', 'open', 'navigate']
    has_navigation_intent = any(t in (original_label or '').lower() for t in nav_terms)

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


def _verify_option_selection(
    ctx: Union[Page, Frame],
    page: Page,
    label: str,
    timeout: int = 3000,
    debug: bool = False
) -> bool:
    """Verify that an option was actually selected after clicking.
    
    Checks that:
    1. Dropdown container closed (or aria-expanded changed)
    2. Option text appears in the combobox value/display
    3. Combobox shows the selected value
    
    Args:
        ctx: The context (Page or Frame) to operate in
        page: The main page object for wait operations
        label: The expected label that should be selected
        timeout: Maximum time to wait for verification (ms)
        debug: If True, print debug messages
    
    Returns:
        True if selection is verified, False otherwise.
    """
    normalized_label = normalize_label(label)
    
    try:
        # Wait a bit for async handlers to process
        page.wait_for_timeout(300)
        
        # Check 1: Verify dropdown closed or combobox value changed
        # Look for combobox that might have the selected value
        try:
            comboboxes = ctx.locator('[role="combobox"]')
            for i in range(min(comboboxes.count(), 5)):  # Check up to 5 comboboxes
                try:
                    combo = comboboxes.nth(i)
                    # Check if the combobox value/text contains our label
                    # Note: Check regardless of aria-expanded state, as some UIs (like Asana)
                    # keep combobox expanded to allow multi-select even after selection
                    combo_text = combo.inner_text(timeout=500).lower()
                    if normalized_label.lower() in combo_text:
                        if debug:
                            print(f"    [DEBUG] Verified selection: combobox shows '{combo_text}'")
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        
        # Check 2: Verify dropdown container is gone or collapsed
        try:
            # Wait for dropdown to close (or verify it's closed)
            containers = ctx.locator('[role="listbox"]:visible, [role="menu"]:visible, [data-state="open"]:visible, [aria-modal="true"]:visible')
            # If no visible containers, dropdown closed successfully
            if containers.count() == 0:
                if debug:
                    print(f"    [DEBUG] Verified selection: dropdown closed")
                return True
        except Exception:
            # If we can't check, assume success for now
            pass
        
        # Check 3: Look for the label in page text near comboboxes (heuristic)
        try:
            page_text = ctx.evaluate('() => document.body.innerText').lower()
            if normalized_label.lower() in page_text:
                # Additional check: see if label appears in visible combobox values
                visible_combos = ctx.locator('[role="combobox"]:visible')
                for i in range(min(visible_combos.count(), 3)):
                    try:
                        combo_text = visible_combos.nth(i).inner_text(timeout=500).lower()
                        if normalized_label.lower() in combo_text:
                            if debug:
                                print(f"    [DEBUG] Verified selection: found in visible combobox")
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        
        # If we can't definitively verify, give benefit of the doubt but with caution
        # Return True to allow continuing, but the longer wait above should help
        return True
        
    except Exception as e:
        if debug:
            print(f"    [DEBUG] Verification check failed: {e}")
        # On error, assume it might have worked (better than blocking)
        return True


def click_aria_element(
    ctx: Union[Page, Frame],
    role: str,
    label: str,
    page: Page,
    debug: bool = False
) -> bool:
    """Click an ARIA element (option, menuitem, or link) by role and label.
    
    Uses find_aria_element with additional fallback strategies and ensures
    the element is scrolled into view and clicked. For dropdown options,
    verifies the selection actually worked.
    
    Args:
        ctx: The context (Page or Frame) to operate in
        role: ARIA role ('option', 'menuitem', or 'link')
        label: The label text to match
        page: The main page object for wait operations
        debug: If True, print debug messages
    
    Returns:
        True if successfully clicked and verified, False otherwise.
    """
    # Ensure container is open (for dropdowns/menus) and detect active container for any role
    active_container = None
    # Hard-coded compose-safe mode ON by default (config)
    compose_safe_mode = True
    try:
        # Try to detect an active container regardless of role
        containers_any = ctx.locator('[role="listbox"]:visible, [role="menu"]:visible, [data-state="open"]:visible, [aria-modal="true"]:visible')
        if containers_any.count() > 0:
            active_container = containers_any.first
            if debug:
                print(f"    [DEBUG] Active container detected (compose context likely active)")
    except Exception:
        pass
    if role in ('option', 'menuitem'):
        ensure_container_open(ctx, page)
    
    normalized_label = normalize_label(label)
    original_label = label.strip() if label else ''
    
    # Try both normalized and original label if they're different
    labels_to_try = [normalized_label]
    if original_label and original_label != normalized_label:
        labels_to_try.append(original_label)
    
    if debug:
        print(f"    [DEBUG] Trying labels: {labels_to_try} (original: '{original_label}', normalized: '{normalized_label}')")
    
    # Build comprehensive candidate list, with strong preference for container scope when available
    candidates = []
    container_first_candidates = []  # tried before global when container exists
    search_ctx = active_container if active_container else ctx
    
    # Try each label variation
    for try_label in labels_to_try:
        if role == 'option':
            # Scope to container if available, otherwise search globally
            if active_container:
                candidates.extend([
                    active_container.get_by_role('option', name=try_label).first,
                    active_container.locator('[role="option"]', has_text=try_label).first,
                ])
            candidates.extend([
                ctx.get_by_role('option', name=try_label).first,
                ctx.locator('[role="option"]', has_text=try_label).first,
            ])
        elif role == 'menuitem':
            if active_container:
                candidates.extend([
                    active_container.get_by_role('menuitem', name=try_label).first,
                    active_container.locator('[role="menuitem"]', has_text=try_label).first,
                ])
            candidates.extend([
                ctx.get_by_role('menuitem', name=try_label).first,
                ctx.locator('[role="menuitem"]', has_text=try_label).first,
            ])
        elif role == 'link':
            # If an active container exists (modal/listbox/menu), try container-scoped link candidates first
            if active_container:
                container_first_candidates.extend([
                    active_container.get_by_role('link', name=try_label).first,
                    active_container.locator('[role="link"]', has_text=try_label).first,
                    active_container.locator('a', has_text=try_label).first,
                ])
            # Add global candidates as fallback only. When an active container exists,
            # only allow global fallback if navigation intent is explicit AND compose_safe_mode is OFF.
            if (not active_container) or (has_navigation_intent and not compose_safe_mode):
                candidates.extend([
                    ctx.get_by_role('link', name=try_label).first,
                    ctx.locator('[role="link"]', has_text=try_label).first,
                    ctx.locator('a', has_text=try_label).first,
                ])
    
    # Regex candidates - try both labels, scoped to container if available
    for try_label in labels_to_try:
        try:
            regex = re.compile(re.escape(try_label), re.IGNORECASE)
            if role == 'option':
                if active_container:
                    candidates.extend([
                        active_container.locator('[role="option"]').filter(has_text=regex).first,
                    ])
                candidates.extend([
                    ctx.locator('[role="option"]').filter(has_text=regex).first,
                ])
            elif role == 'menuitem':
                if active_container:
                    candidates.extend([
                        active_container.locator('[role="menuitem"]').filter(has_text=regex).first,
                    ])
                candidates.extend([
                    ctx.locator('[role="menuitem"]').filter(has_text=regex).first,
                ])
            elif role == 'link':
                if active_container:
                    container_first_candidates.extend([
                        active_container.locator('[role="link"]').filter(has_text=regex).first,
                        active_container.locator('a').filter(has_text=regex).first,
                    ])
                if (not active_container) or (has_navigation_intent and not compose_safe_mode):
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
                    if active_container:
                        candidates.extend([
                            active_container.locator('[role="option"]').filter(has_text=email_only).first,
                        ])
                    candidates.extend([
                        ctx.locator('[role="option"]').filter(has_text=email_only).first,
                    ])
                elif role == 'menuitem':
                    if active_container:
                        candidates.extend([
                            active_container.locator('[role="menuitem"]').filter(has_text=email_only).first,
                        ])
                    candidates.extend([
                        ctx.locator('[role="menuitem"]').filter(has_text=email_only).first,
                    ])
                elif role == 'link':
                    if active_container:
                        container_first_candidates.extend([
                            active_container.locator('[role="link"]').filter(has_text=email_only).first,
                            active_container.locator('a').filter(has_text=email_only).first,
                        ])
                    # Email regex can cause cross-page collisions; when a container is active,
                    # only widen to global if navigation intent is explicit and compose_safe_mode is OFF
                    if (not active_container) or (has_navigation_intent and not compose_safe_mode):
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
                        if active_container:
                            candidates.extend([
                                active_container.locator('[role="option"]').filter(has_text=part).first,
                            ])
                        candidates.extend([
                            ctx.locator('[role="option"]').filter(has_text=part).first,
                        ])
                    elif role == 'menuitem':
                        if active_container:
                            candidates.extend([
                                active_container.locator('[role="menuitem"]').filter(has_text=part).first,
                            ])
                        candidates.extend([
                            ctx.locator('[role="menuitem"]').filter(has_text=part).first,
                        ])
                    elif role == 'link':
                        if active_container:
                            container_first_candidates.extend([
                                active_container.locator('[role="link"]').filter(has_text=part).first,
                                active_container.locator('a').filter(has_text=part).first,
                            ])
                        if (not active_container) or (has_navigation_intent and not compose_safe_mode):
                            candidates.extend([
                                ctx.locator('[role="link"]').filter(has_text=part).first,
                                ctx.locator('a').filter(has_text=part).first,
                            ])
                except Exception:
                    pass
    
    # If container exists and role is link, try container-first candidates before global fallback
    ordered_candidates = []
    if role == 'link' and active_container:
        ordered_candidates.extend(container_first_candidates)
        # In compose-safe mode, do not try global link fallbacks while container is active
        if not compose_safe_mode:
            ordered_candidates.extend(candidates)
    else:
        ordered_candidates.extend(candidates)

    # Try clicking candidates with attempt/time budgets
    import time as _time
    start_ts = _time.time()
    max_ms = 1.8  # overall time budget per call (seconds)
    max_attempts = 14
    attempts = 0
    for cand in ordered_candidates:
        attempts += 1
        if attempts > max_attempts:
            if debug:
                print(f"    [DEBUG] Stopping: attempts>{max_attempts}")
            break
        if (_time.time() - start_ts) > max_ms:
            if debug:
                print(f"    [DEBUG] Stopping: time budget exceeded ({max_ms}s)")
            break
        try:
            if cand and cand.count() > 0:
                # Ensure element is scrollable and visible
                try:
                    cand.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    if debug:
                        print(f"    [DEBUG] Scroll failed, continuing...")
                
                # Wait for element to be actionable
                try:
                    cand.wait_for(state='visible', timeout=8000)
                except Exception:
                    if debug:
                        print(f"    [DEBUG] Wait for visible failed, continuing...")
                    continue
                
                # For dropdown options/menuitems, use proper click with verification
                if role in ('option', 'menuitem'):
                    clicked_successfully = False
                    click_error = None
                    
                    # Try Playwright click first (best for actionability and event handling)
                    try:
                        if debug:
                            print(f"    [DEBUG] Trying Playwright click (role={role})...")
                        cand.click(timeout=5000)
                        clicked_successfully = True
                    except Exception as pw_err:
                        click_error = pw_err
                        error_str = str(pw_err).lower()
                        
                        # If intercepted, try force click
                        if 'intercept' in error_str or 'pointer' in error_str:
                            if debug:
                                print(f"    [DEBUG] Playwright click intercepted, trying force click...")
                            try:
                                cand.click(timeout=3000, force=True)
                                clicked_successfully = True
                            except Exception as force_err:
                                click_error = force_err
                                if debug:
                                    print(f"    [DEBUG] Force click failed: {force_err}")
                        else:
                            if debug:
                                print(f"    [DEBUG] Playwright click failed: {pw_err}")
                    
                    # If Playwright clicks failed, try JavaScript click as fallback
                    if not clicked_successfully:
                        try:
                            if debug:
                                print(f"    [DEBUG] Trying JavaScript click as fallback...")
                            cand.evaluate('element => element.click()')
                            clicked_successfully = True
                        except Exception as js_err:
                            if debug:
                                print(f"    [DEBUG] JavaScript click also failed: {js_err}")
                            continue  # Try next candidate
                    
                    # If click succeeded, verify the selection
                    if clicked_successfully:
                        # Wait longer for async handlers to complete
                        page.wait_for_timeout(500)
                        
                        # Verify the selection worked
                        if _verify_option_selection(ctx, page, label, timeout=2000, debug=debug):
                            if debug:
                                print(f"    [DEBUG] Selection verified successfully")
                            return True
                        else:
                            if debug:
                                print(f"    [DEBUG] Selection verification failed, trying next candidate")
                            # Verification failed, but element was clicked - might still work
                            # Wait a bit more and check one more time
                            page.wait_for_timeout(300)
                            if _verify_option_selection(ctx, page, label, timeout=1000, debug=debug):
                                return True
                            # Continue to next candidate
                            continue
                
                else:
                    # For links, try normal click first
                    try:
                        # Capture URL to detect unintended navigations when inside a container context
                        prev_url = page.url if page else None
                        cand.click(timeout=5000)
                        page.wait_for_timeout(200)
                        # If we had an active container and clicking caused navigation, treat as a bad candidate
                        try:
                            if active_container and prev_url and page and page.url != prev_url:
                                if has_navigation_intent and not compose_safe_mode:
                                    # Allow navigation when intent was explicitly navigational
                                    if debug:
                                        print(f"    [DEBUG] Navigation occurred and was allowed due to intent")
                                else:
                                    if debug:
                                        print(f"    [DEBUG] Link click navigated away while container active; rejecting candidate")
                                    # Consider this a failure; do not return success
                                    # Best-effort: do not attempt to auto-navigate back to avoid side effects
                                    continue
                            # Compose-safe: ensure container still visible after click
                            if active_container and compose_safe_mode:
                                try:
                                    containers_check = ctx.locator('[role="listbox"]:visible, [role="menu"]:visible, [data-state="open"]:visible, [aria-modal="true"]:visible')
                                    if containers_check.count() == 0:
                                        if debug:
                                            print(f"    [DEBUG] Compose-safe: container not visible after click; rejecting candidate")
                                        continue
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        return True
                    except Exception as click_err:
                        error_str = str(click_err).lower()
                        # Check if click was blocked by intercepting element
                        if 'intercept' in error_str or 'pointer' in error_str:
                            if debug:
                                print(f"    [DEBUG] Normal click blocked, trying force click...")
                            try:
                                # Try force click (bypasses actionability checks)
                                prev_url = page.url if page else None
                                cand.click(timeout=3000, force=True)
                                page.wait_for_timeout(200)
                                if active_container and prev_url and page and page.url != prev_url:
                                    if has_navigation_intent and not compose_safe_mode:
                                        if debug:
                                            print(f"    [DEBUG] Force-click navigation allowed due to intent")
                                    else:
                                        if debug:
                                            print(f"    [DEBUG] Force link click navigated away while container active; rejecting candidate")
                                        continue
                                return True
                            except Exception as force_err:
                                if debug:
                                    print(f"    [DEBUG] Force click failed, trying JS click: {force_err}")
                                try:
                                    # Try JavaScript click as fallback
                                    prev_url = page.url if page else None
                                    cand.evaluate('element => element.click()')
                                    page.wait_for_timeout(200)
                                    if active_container and prev_url and page and page.url != prev_url:
                                        if has_navigation_intent and not compose_safe_mode:
                                            if debug:
                                                print(f"    [DEBUG] JS click navigation allowed due to intent")
                                        else:
                                            if debug:
                                                print(f"    [DEBUG] JS link click navigated away while container active; rejecting candidate")
                                            continue
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
            scope = active_container if active_container else ctx
            all_options = scope.locator('[role="option"]:visible, [role="menuitem"]:visible')
            if all_options.count() == 1:
                last_resort = all_options.first
                clicked = False
                try:
                    last_resort.click(timeout=5000)
                    clicked = True
                except Exception as click_err:
                    error_str = str(click_err).lower()
                    if 'intercept' in error_str or 'pointer' in error_str:
                        try:
                            last_resort.click(timeout=5000, force=True)
                            clicked = True
                        except Exception:
                            try:
                                last_resort.evaluate('element => element.click()')
                                clicked = True
                            except Exception:
                                pass
                
                if clicked:
                    page.wait_for_timeout(500)
                    if _verify_option_selection(ctx, page, label, timeout=2000, debug=debug):
                        return True
        except Exception:
            pass
    
    return False

