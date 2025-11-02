"""Shared combobox/dropdown detection and hint generation utilities."""
from typing import Any, Dict, List, Optional, Tuple
from ...drivers.utils.selector_normalizer import is_placeholder_text


def is_combobox_field(label: str, interactables: List[Dict[str, Any]]) -> bool:
    """Check if a field label indicates combobox behavior.
    
    Args:
        label: The field label to check
        interactables: Current interactable elements on the page
        
    Returns:
        True if the field appears to be a combobox field
    """
    label_lower = label.lower()
    
    # Direct combobox indicators
    combobox_indicators = [
        'combobox',
        'type the name',
        'recipient',
        'to',
        'email',
        'address',
        'invite'
    ]
    
    if any(indicator in label_lower for indicator in combobox_indicators):
        return True
    
    # Check if any element with this label is a combobox
    if any(
        elem.get('role') == 'combobox' and 
        (label_lower in (elem.get('label') or '').lower() or 
         label_lower in (elem.get('placeholder') or '').lower())
        for elem in interactables
    ):
        return True
    
    # Check if field has combobox-like behavior (shows dropdown after typing)
    if any(
        elem.get('role') in ['textbox', 'combobox'] and 
        label_lower in (elem.get('label') or '').lower() and
        any(keyword in (elem.get('placeholder') or '').lower() for keyword in 
            ['email', 'recipient', 'to', 'invite', 'type', 'add', 'enter'])
        for elem in interactables
    ):
        return True
    
    return False


def find_combobox_options(
    typed_text: str,
    interactables: List[Dict[str, Any]],
    prev_elements: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Find dropdown options that appeared after typing in a combobox field.
    
    Returns:
        Tuple of (newly_appeared_options, matching_options, all_newly_appeared_options, existing_with_label)
    """
    prev_selectors = {elem.get('selector', '') for elem in prev_elements}
    typed_text_lower = typed_text.lower()
    
    # Find newly appeared elements
    newly_appeared = [
        elem for elem in interactables
        if elem.get('selector', '') not in prev_selectors
    ]
    
    # Find ALL newly appeared dropdown options
    all_newly_appeared_options = [
        elem for elem in interactables
        if elem.get('role') == 'option' and 
        elem.get('selector', '') not in prev_selectors
    ]
    
    # Find options matching typed text
    matching_options = [
        elem for elem in interactables
        if elem.get('role') == 'option' and 
        (typed_text_lower in (elem.get('label') or '').lower() or 
         (elem.get('label') or '').lower() in typed_text_lower or
         # Also match if option contains typed email
         any(part in (elem.get('label') or '').lower() for part in typed_text.split('@') 
             if '@' in typed_text and len(part) > 2))
    ]
    
    # Identify which matching options are newly appeared
    newly_appeared_options = [
        opt for opt in matching_options
        if opt.get('selector', '') not in prev_selectors
    ]
    
    # If no matching options but we have newly appeared options, use those
    if not newly_appeared_options and all_newly_appeared_options:
        newly_appeared_options = all_newly_appeared_options
    
    # Find existing elements with similar labels (background elements)
    existing_elements_with_label = [
        elem for elem in interactables
        if elem.get('selector', '') in prev_selectors and
        (typed_text_lower in (elem.get('label') or '').lower() or 
         (elem.get('label') or '').lower() in typed_text_lower)
    ]
    
    return newly_appeared_options, matching_options, all_newly_appeared_options, existing_elements_with_label


def filter_placeholder_options(
    options: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter out placeholder text from options and return filtered + placeholder lists.
    
    Returns:
        Tuple of (filtered_options, placeholder_elements)
    """
    filtered = [
        opt for opt in options
        if not is_placeholder_text(opt.get('label', ''))
    ]
    placeholder_elements = [
        elem for elem in options
        if is_placeholder_text(elem.get('label', ''))
    ]
    return filtered, placeholder_elements


def sort_options_by_dom_order(
    options: List[Dict[str, Any]],
    interactables: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Sort options by their order in the DOM (interactables list).
    
    Args:
        options: List of option elements to sort
        interactables: Full list of interactables (maintains DOM order)
        
    Returns:
        Sorted list of options
    """
    options_with_order = []
    for opt in options:
        try:
            idx = next(i for i, elem in enumerate(interactables) 
                      if elem.get('selector') == opt.get('selector'))
            options_with_order.append((idx, opt))
        except StopIteration:
            options_with_order.append((999, opt))  # Not found, put at end
    
    return [opt for _, opt in sorted(options_with_order)]


def has_disabled_submit_button(interactables: List[Dict[str, Any]]) -> bool:
    """Check if there's a disabled submit/send button visible.
    
    Args:
        interactables: Current interactable elements
        
    Returns:
        True if a disabled submit button is found
    """
    submit_keywords = ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish', 'invite']
    
    return any(
        (elem.get('role') == 'button' or elem.get('role') == 'link') and
        elem.get('disabled', False) and
        any(term in (elem.get('label') or '').lower() for term in submit_keywords)
        for elem in interactables
    )


def build_combobox_hints_for_scoring(
    typed_text: str,
    interactables: List[Dict[str, Any]],
    prev_elements: List[Dict[str, Any]]
) -> List[str]:
    """Build combobox-related hints for the scoring node.
    
    Returns:
        List of hint strings (empty if no combobox situation detected)
    """
    hints = []
    
    newly_appeared_options, matching_options, all_newly_appeared_options, existing_elements_with_label = \
        find_combobox_options(typed_text, interactables, prev_elements)
    
    has_disabled_submit = has_disabled_submit_button(interactables)
    
    # Filter out placeholder text
    options_to_use = newly_appeared_options if newly_appeared_options else \
                    (matching_options if matching_options else all_newly_appeared_options)
    
    if options_to_use:
        filtered_options, placeholder_elements = filter_placeholder_options(options_to_use)
        if filtered_options:
            options_to_use = filtered_options
        
        # Warn about placeholder text
        if placeholder_elements:
            placeholder_labels = [elem.get('label', 'N/A') for elem in placeholder_elements[:2]]
            hints.append(
                f"⚠️ WARNING: Placeholder/example text detected ({', '.join(placeholder_labels)}) - "
                f"these are NOT real options. Score placeholder elements 0-1. Do NOT select placeholder text."
            )
    
    if options_to_use:
        # Sort by DOM order
        options_sorted = sort_options_by_dom_order(options_to_use, interactables)
        
        first_option = options_sorted[0] if options_sorted else None
        first_option_label = first_option.get('label', 'N/A') if first_option else 'N/A'
        first_option_selector = first_option.get('selector', 'N/A') if first_option else 'N/A'
        other_options = options_sorted[1:3] if len(options_sorted) > 1 else []
        
        option_labels = [opt.get('label', 'N/A') for opt in options_sorted[:3]]
        option_selectors = [opt.get('selector', 'N/A') for opt in options_sorted[:3]]
        existing_labels = [elem.get('label', 'N/A') for elem in existing_elements_with_label[:3]] \
                         if existing_elements_with_label else []
        
        if has_disabled_submit:
            if first_option:
                hints.append(
                    f"🔗 COMBOBOX VALIDATION REQUIRED: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                    f"The FIRST option '{first_option_label}' (selector: {first_option_selector}) is the PRIMARY/DEFAULT selection - score it 9-10. "
                    f"{f'Other options ({[opt.get("label") for opt in other_options]}) are alternatives - score them 7-8. ' if other_options else ''}"
                    f"{f'Background elements with similar labels ({existing_labels}) existed before typing - these are page links, NOT dropdown options. ' if existing_labels else ''}"
                    f"The Submit/Send/Invite button is DISABLED until you select one of the NEWLY APPEARED dropdown options. "
                    f"Score the FIRST option '{first_option_label}' 9-10. Score other newly appeared options 7-8. "
                    f"Score background elements that existed before typing 0-2."
                )
            else:
                hints.append(
                    f"🔗 COMBOBOX VALIDATION REQUIRED: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                    f"These options (selectors: {', '.join(option_selectors[:2])}) are NEWLY APPEARED and are the dropdown options to select. "
                    f"{f'Background elements with similar labels ({existing_labels}) existed before typing - these are page links, NOT dropdown options. ' if existing_labels else ''}"
                    f"The Submit/Send/Invite button is DISABLED until you select one of the NEWLY APPEARED dropdown options. "
                    f"Score NEWLY APPEARED options (selectors: {', '.join(option_selectors[:2])}) 8-9. "
                    f"Score background elements that existed before typing 0-2."
                )
        else:
            if first_option:
                hints.append(
                    f"🔗 COMBOBOX SELECTION: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                    f"The FIRST option '{first_option_label}' (selector: {first_option_selector}) is the PRIMARY/DEFAULT selection - score it 9-10. "
                    f"{f'Other options ({[opt.get("label") for opt in other_options]}) are alternatives - score them 7-8. ' if other_options else ''}"
                    f"{f'Background elements ({existing_labels}) with similar labels existed before - these are page links, NOT the dropdown. ' if existing_labels else ''}"
                    f"Select the FIRST option '{first_option_label}' to validate the input. "
                    f"Score the FIRST option 9-10. Score other newly appeared options 7-8. Score background elements that existed before typing 0-2."
                )
            else:
                hints.append(
                    f"🔗 COMBOBOX SELECTION: After typing '{typed_text}' into field, new dropdown options appeared: {', '.join(option_labels)}. "
                    f"These options (selectors: {', '.join(option_selectors[:2])}) are NEWLY APPEARED after your typing action. "
                    f"{f'Background elements ({existing_labels}) with similar labels existed before - these are page links, NOT the dropdown. ' if existing_labels else ''}"
                    f"Select one of the NEWLY APPEARED dropdown options to validate the input. "
                    f"Score NEWLY APPEARED options 8-9. Score background elements that existed before typing 0-2."
                )
    elif matching_options:
        # Fallback: We have matching options but couldn't determine which are new
        option_labels = [opt.get('label', 'N/A') for opt in matching_options[:3]]
        option_selectors = [opt.get('selector', 'N/A') for opt in matching_options[:3]]
        if has_disabled_submit:
            hints.append(
                f"🔗 COMBOBOX VALIDATION: Dropdown options matching '{typed_text}' appeared: {', '.join(option_labels)}. "
                f"Score dropdown options (role='option', selectors: {', '.join(option_selectors[:2])}) 8-9. "
                f"Penalize background elements (role='link'/'button') with similar labels."
            )
        else:
            hints.append(
                f"🔗 COMBOBOX SELECTION: Select dropdown option matching '{typed_text}' (selectors: {', '.join(option_selectors[:2])}) to validate input. "
                f"Score options (role='option') 8-9, penalize background links."
            )
    
    return hints


def build_combobox_hints_for_decision(
    typed_text: str,
    candidates: List[Dict[str, Any]],
    interactables: List[Dict[str, Any]],
    prev_elements: List[Dict[str, Any]],
    scored_actions: List
) -> List[str]:
    """Build combobox-related hints for the decision node.
    
    Returns:
        List of hint strings (empty if no combobox situation detected)
    """
    hints = []
    
    prev_selectors = {elem.get('selector', '') for elem in prev_elements}
    typed_text_lower = typed_text.lower()
    
    # Find newly appeared option candidates
    all_newly_appeared_option_candidates = [
        c for c in candidates
        if c.get('action_type') == 'click' and
        'role=option' in c.get('selector', '') and
        c.get('selector', '') not in prev_selectors
    ]
    
    # Find matching candidates
    matching_candidates = [
        c for c in candidates
        if c.get('action_type') == 'click' and
        (typed_text_lower in (c.get('label') or '').lower() or
         (c.get('label') or '').lower() in typed_text_lower or
         # Also match if option contains typed email
         any(part in (c.get('label') or '').lower() for part in typed_text.split('@') 
             if '@' in typed_text and len(part) > 2))
    ]
    
    # Identify which are newly appeared
    newly_appeared_candidates = [
        c for c in matching_candidates
        if c.get('selector', '') not in prev_selectors
    ]
    
    if not newly_appeared_candidates and all_newly_appeared_option_candidates:
        newly_appeared_candidates = all_newly_appeared_option_candidates
    
    existing_candidates_with_label = [
        c for c in matching_candidates
        if c.get('selector', '') in prev_selectors
    ]
    
    if not matching_candidates:
        return hints
    
    # Check for disabled submit button
    has_disabled_submit_candidate = False
    if scored_actions:
        for c in candidates:
            label_lower = (c.get('label') or '').lower()
            if label_lower in ['send', 'submit', 'save', 'create', 'post', 'confirm', 'done', 'finish']:
                for a in scored_actions[:10]:
                    if (a.label.lower() == label_lower if hasattr(a, 'label') else False) and a.score <= 2:
                        has_disabled_submit_candidate = True
                        break
                if has_disabled_submit_candidate:
                    break
    
    has_disabled_submit_element = has_disabled_submit_button(interactables)
    
    if newly_appeared_candidates:
        # Sort by order
        candidates_with_order = []
        for cand in newly_appeared_candidates:
            try:
                idx = next(i for i, c in enumerate(candidates) 
                          if c.get('selector') == cand.get('selector'))
                candidates_with_order.append((idx, cand))
            except StopIteration:
                candidates_with_order.append((999, cand))
        sorted_newly_appeared = [cand for _, cand in sorted(candidates_with_order)]
        
        first_candidate = sorted_newly_appeared[0] if sorted_newly_appeared else None
        first_label = first_candidate.get('label', 'N/A') if first_candidate else 'N/A'
        first_selector = first_candidate.get('selector', 'N/A') if first_candidate else 'N/A'
        other_candidates = sorted_newly_appeared[1:2] if len(sorted_newly_appeared) > 1 else []
        
        option_labels = [c.get('label', 'N/A') for c in sorted_newly_appeared[:3]]
        option_selectors = [c.get('selector', 'N/A') for c in sorted_newly_appeared[:3]]
        existing_labels = [c.get('label', 'N/A') for c in existing_candidates_with_label[:2]] \
                         if existing_candidates_with_label else []
        
        if has_disabled_submit_element or has_disabled_submit_candidate:
            if first_candidate:
                hints.append(
                    f"🔗 COMBOBOX VALIDATION: After typing, NEW dropdown options appeared ({', '.join(option_labels)}). "
                    f"The FIRST option '{first_label}' (selector: {first_selector}) is the PRIMARY/DEFAULT selection - SELECT THIS ONE. "
                    f"{f'Other options ({[c.get("label") for c in other_candidates]}) are alternatives. ' if other_candidates else ''}"
                    f"{f'AVOID existing candidates ({existing_labels}) - these existed before typing and are background page elements, NOT dropdown options. ' if existing_labels else ''}"
                    f"Selecting the FIRST option '{first_label}' will validate and enable Send/Invite button. AVOID clicking disabled buttons."
                )
            else:
                hints.append(
                    f"🔗 COMBOBOX VALIDATION: After typing, NEW dropdown options appeared ({', '.join(option_labels)}) - these are the ones to select. "
                    f"Select NEWLY APPEARED candidates (selectors: {', '.join(option_selectors[:2])}) to validate and enable Send button. "
                    f"{f'AVOID existing candidates ({existing_labels}) - these existed before typing and are background page elements, NOT dropdown options. ' if existing_labels else ''}"
                    f"AVOID clicking disabled Send button."
                )
        else:
            if first_candidate:
                hints.append(
                    f"🔗 COMBOBOX SELECTION: After typing, NEW dropdown options appeared ({', '.join(option_labels)}). "
                    f"The FIRST option '{first_label}' (selector: {first_selector}) is the PRIMARY/DEFAULT selection - SELECT THIS ONE. "
                    f"{f'Other options ({[c.get("label") for c in other_candidates]}) are alternatives. ' if other_candidates else ''}"
                    f"{f'AVOID existing candidates ({existing_labels}) - these existed before typing and are background page elements, NOT dropdown options. ' if existing_labels else ''}"
                    f"Select the FIRST option '{first_label}' to validate the input."
                )
            else:
                hints.append(
                    f"🔗 COMBOBOX SELECTION: After typing, NEW dropdown options appeared ({', '.join(option_labels)}). "
                    f"Select NEWLY APPEARED candidates (selectors: {', '.join(option_selectors[:2])}). "
                    f"{f'AVOID existing candidates ({existing_labels}) - these are background page elements, NOT the dropdown. ' if existing_labels else ''}"
                )
    elif matching_candidates:
        option_labels = [c.get('label', 'N/A') for c in matching_candidates[:2]]
        option_selectors = [c.get('selector', 'N/A') for c in matching_candidates[:2]]
        if has_disabled_submit_element or has_disabled_submit_candidate:
            hints.append(
                f"🔗 COMBOBOX VALIDATION: Select matching dropdown option ({', '.join(option_labels)}) to enable Send button. "
                f"Prefer candidates with role='option' (selectors: {', '.join(option_selectors[:2])}). "
                f"AVOID clicking disabled Send button."
            )
        else:
            option_candidates = [c for c in matching_candidates if 'role=option' in (c.get('selector', ''))]
            if option_candidates:
                hints.append(
                    f"🔗 COMBOBOX SELECTION: Prefer candidates with role='option' (selectors: {', '.join([c.get('selector', 'N/A') for c in option_candidates[:2]])}). "
                    f"AVOID candidates with role='link' - these are background elements."
                )
    else:
        option_labels = [c.get('label') for c in matching_candidates[:2] if c.get('label')]
        if option_labels:
            hints.append(
                f"⚠️ REDUNDANCY WARNING: Recently typed '{typed_text}' into combobox. "
                f"Candidate dropdown options matching this text ({', '.join(option_labels)}) are likely redundant. "
                f"AVOID selecting these; prefer moving to next field, submitting, or other productive actions."
            )
    
    return hints

