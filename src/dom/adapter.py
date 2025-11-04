"""Adapter to convert gRPC interactables to browser-use format."""
from typing import List, Dict, Any
from .types import (
	InteractableElement, SimplifiedNode, SerializedDOMState,
	SelectorMap, NodeType
)


def convert_interactables_to_dom_state(
	interactables: List[Dict[str, Any]],
	max_elements: int = 200
) -> SerializedDOMState:
	"""
	Convert gRPC interactables list to SerializedDOMState.
	
	Args:
		interactables: List of interactable element dicts from gRPC
		max_elements: Maximum number of elements to include
		
	Returns:
		SerializedDOMState with browser-use format ready for LLM
	"""
	# Cap interactables
	capped_interactables = interactables[:max_elements]
	
	# Convert to InteractableElement objects and assign indices
	element_map: Dict[int, InteractableElement] = {}
	selector_map: SelectorMap = {}
	
	# Use real backend_node_id from gRPC if available, otherwise assign sequential
	backend_node_id_counter = 1  # For elements without backend_node_id
	
	for i, inter_dict in enumerate(capped_interactables):
		# Use real backend_node_id from CDP if available (non-zero), otherwise assign sequential
		real_backend_id = inter_dict.get('backend_node_id', 0)
		if real_backend_id == 0:
			# No real backend_node_id, assign sequential (but skip 0)
			real_backend_id = backend_node_id_counter
			backend_node_id_counter += 1
		
		element = InteractableElement(
			role=inter_dict.get('role', ''),
			label=inter_dict.get('label', ''),
			selector=inter_dict.get('selector', ''),
			disabled=inter_dict.get('disabled', False),
			tag=inter_dict.get('tag', 'div'),
			classes=list(inter_dict.get('classes', [])),
			id=inter_dict.get('id', ''),
			href=inter_dict.get('href', ''),
			type=inter_dict.get('type', ''),
			placeholder=inter_dict.get('placeholder', ''),
			text_content=inter_dict.get('label', ''),
			backend_node_id=real_backend_id,  # Use real backend_node_id from CDP
		)
		
		# Build attributes dict
		element.attributes = {}
		if element.id:
			element.attributes['id'] = element.id
		if element.type:
			element.attributes['type'] = element.type
		if element.placeholder:
			element.attributes['placeholder'] = element.placeholder
		if element.href:
			element.attributes['href'] = element.href
		if element.role:
			element.attributes['role'] = element.role
		if element.disabled:
			element.attributes['disabled'] = 'true'
		if element.classes:
			element.attributes['class'] = ' '.join(element.classes)
		
		element_map[i] = element
		selector_map[real_backend_id] = element  # Use real backend_node_id as key
	
	# Build simplified tree structure
	# Since we don't have full DOM hierarchy from gRPC, we'll create a flat-ish structure
	# Group elements by common patterns (e.g., forms, lists)
	root = _build_simplified_tree(list(element_map.values()), selector_map)
	
	return SerializedDOMState(
		_root=root,
		selector_map=selector_map
	)


def _build_simplified_tree(
	elements: List[InteractableElement],
	selector_map: SelectorMap
) -> SimplifiedNode:
	"""
	Build a simplified tree structure from flat list of elements.
	
	Since we don't have full DOM hierarchy from gRPC, we create a reasonable structure:
	- Group related elements (forms, lists)
	- Create container nodes for logical groupings
	"""
	if not elements:
		return None
	
	# Create root container
	root_element = InteractableElement(
		role='document',
		label='Page',
		selector='body',
		disabled=False,
		tag='body',
		classes=[],
		id='',
		href='',
		type='',
		placeholder='',
		text_content='',
		backend_node_id=0,
	)
	
	root = SimplifiedNode(
		original_element=root_element,
		children=[],
		should_display=False,  # Don't show root in output
		is_interactive=False,
		depth=0
	)
	
	# For now, create a flat structure with all interactables as direct children
	# In a more sophisticated version, we could group by selectors or roles
	for element in elements:
		child_node = SimplifiedNode(
			original_element=element,
			children=[],
			should_display=True,
			is_interactive=True,  # All these are interactive
			is_new=False,
			depth=1
		)
		root.children.append(child_node)
	
	return root


def get_selector_from_index(index: int, selector_map: SelectorMap) -> str | None:
	"""Get selector for an element by its backend_node_id index."""
	if index in selector_map:
		return selector_map[index].selector
	return None


def get_element_from_index(index: int, selector_map: SelectorMap) -> InteractableElement | None:
	"""Get element for an index."""
	if index in selector_map:
		return selector_map[index]
	return None

