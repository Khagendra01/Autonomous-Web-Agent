"""Enhanced DOM processing inspired by browser-use's advanced DOM handling."""
from typing import Dict, Any, List, Optional
import json
import hashlib


class DOMElement:
    """Represents a processed interactive DOM element with metadata."""
    
    def __init__(
        self,
        index: int,
        tag_name: str,
        role: str,
        label: str,
        selector: str,
        attributes: Dict[str, Any],
        bounds: Optional[Dict[str, float]] = None,
        is_visible: bool = True,
        is_interactive: bool = True,
        text_content: Optional[str] = None,
    ):
        self.index = index
        self.tag_name = tag_name
        self.role = role
        self.label = label
        self.selector = selector
        self.attributes = attributes
        self.bounds = bounds
        self.is_visible = is_visible
        self.is_interactive = is_interactive
        self.text_content = text_content or label
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for LLM consumption."""
        return {
            'index': self.index,
            'tag': self.tag_name,
            'role': self.role,
            'label': self.label,
            'selector': self.selector,
            'text': self.text_content,
            'visible': self.is_visible,
            'interactive': self.is_interactive,
            **self.attributes,
        }
    
    def __repr__(self) -> str:
        return f"DOMElement(index={self.index}, {self.role} '{self.label}')"


class DOMSelectorMap:
    """Maps numeric indices to DOM elements for LLM-friendly element selection."""
    
    def __init__(self):
        self._elements: List[DOMElement] = []
        self._index_map: Dict[int, DOMElement] = {}
    
    def add_element(self, element: DOMElement) -> None:
        """Add an element to the map."""
        self._elements.append(element)
        self._index_map[element.index] = element
    
    def get_element(self, index: int) -> Optional[DOMElement]:
        """Get element by index."""
        return self._index_map.get(index)
    
    def get_all(self) -> List[DOMElement]:
        """Get all elements."""
        return self._elements.copy()
    
    def filter_interactive(self) -> List[DOMElement]:
        """Get only interactive elements."""
        return [e for e in self._elements if e.is_interactive]
    
    def serialize_for_llm(self, max_length: int = 40000) -> str:
        """Serialize elements in a format optimized for LLM consumption.
        
        Format similar to browser-use's selector_map representation:
        ```
        [0] button 'Submit' (role=button, selector=button.submit)
        [1] textbox 'Email' (role=textbox, placeholder=Enter email)
        ...
        ```
        """
        lines = []
        for element in self._elements:
            if not element.is_interactive or not element.is_visible:
                continue
            
            # Build element description
            parts = [f"[{element.index}]"]
            
            # Add role and label
            if element.role:
                parts.append(element.role)
            if element.label:
                parts.append(f"'{element.label}'")
            
            # Add key attributes in parentheses
            attrs = []
            if element.tag_name:
                attrs.append(f"tag={element.tag_name}")
            if element.selector and not element.selector.startswith('role='):
                # Only add selector if it's not a role selector
                attrs.append(f"selector={element.selector}")
            for key in ['placeholder', 'type', 'id', 'href']:
                if key in element.attributes and element.attributes[key]:
                    attrs.append(f"{key}={element.attributes[key]}")
            
            if attrs:
                parts.append(f"({', '.join(attrs)})")
            
            lines.append(' '.join(parts))
        
        result = '\n'.join(lines)
        
        # Truncate if too long
        if len(result) > max_length:
            result = result[:max_length] + f"\n... (truncated, showing first {max_length} chars)"
        
        return result
    
    def to_list_dict(self) -> List[Dict[str, Any]]:
        """Convert to list of dictionaries for JSON serialization."""
        return [e.to_dict() for e in self._elements]


def process_interactable_elements(
    raw_elements: List[Dict[str, Any]],
    max_elements: int = 200
) -> DOMSelectorMap:
    """Process raw interactable elements into enhanced DOM structure.
    
    This function:
    1. Filters and validates elements
    2. Assigns numeric indices
    3. Enhances with metadata
    4. Creates a selector map for LLM consumption
    
    Args:
        raw_elements: Raw elements from driver observation
        max_elements: Maximum number of elements to process
        
    Returns:
        DOMSelectorMap with processed elements
    """
    selector_map = DOMSelectorMap()
    
    # Filter and process elements
    valid_elements = []
    for i, raw in enumerate(raw_elements[:max_elements]):
        # Extract key information
        role = raw.get('role', '').lower()
        label = raw.get('label', '') or raw.get('name', '')
        selector = raw.get('selector', '')
        tag = raw.get('tag', '').lower()
        disabled = raw.get('disabled', False)
        
        # Skip non-interactive roles
        if role in {'none', 'presentation'}:
            continue
        
        # Determine if element is interactive
        is_interactive = (
            role in {
                'button', 'link', 'textbox', 'combobox', 'checkbox',
                'radio', 'menuitem', 'option', 'tab', 'slider'
            } or
            tag in {'button', 'a', 'input', 'select', 'textarea'}
        ) and not disabled
        
        # Extract attributes
        attributes = {
            'disabled': disabled,
        }
        for key in ['type', 'placeholder', 'id', 'href', 'classes', 'value']:
            if key in raw and raw[key]:
                attributes[key] = raw[key]
        
        # Create enhanced element
        element = DOMElement(
            index=i,
            tag_name=tag,
            role=role,
            label=label,
            selector=selector,
            attributes=attributes,
            is_visible=True,  # All from driver should be visible
            is_interactive=is_interactive,
            text_content=label,
        )
        
        selector_map.add_element(element)
    
    return selector_map


def create_dom_summary(selector_map: DOMSelectorMap) -> Dict[str, Any]:
    """Create a summary of the DOM state for LLM context.
    
    Similar to browser-use's page statistics extraction.
    """
    elements = selector_map.get_all()
    interactive = selector_map.filter_interactive()
    
    stats = {
        'total_elements': len(elements),
        'interactive_elements': len(interactive),
        'links': len([e for e in interactive if e.role == 'link' or e.tag_name == 'a']),
        'buttons': len([e for e in interactive if e.role == 'button' or e.tag_name == 'button']),
        'inputs': len([e for e in interactive if e.role in {'textbox', 'combobox'} or e.tag_name == 'input']),
    }
    
    return {
        'stats': stats,
        'elements_text': selector_map.serialize_for_llm(),
        'elements_list': selector_map.to_list_dict()[:80],  # Limit for LLM context
    }

