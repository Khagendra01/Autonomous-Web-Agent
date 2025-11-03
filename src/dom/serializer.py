"""DOM tree serializer for LLM consumption (adapted from browser-use)."""
from typing import Optional
from .types import SimplifiedNode, InteractableElement, NodeType
from .utils import cap_text_length


class DOMTreeSerializer:
	"""Serializes interactable elements to browser-use format."""
	
	@staticmethod
	def serialize_tree(node: Optional[SimplifiedNode], include_attributes: list[str], depth: int = 0) -> str:
		"""Serialize the tree to string format matching browser-use."""
		if not node:
			return ''
		
		# Skip rendering excluded nodes
		if node.excluded_by_parent:
			formatted_text = []
			for child in node.children:
				child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, depth)
				if child_text:
					formatted_text.append(child_text)
			return '\n'.join(formatted_text)
		
		formatted_text = []
		depth_str = depth * '\t'
		next_depth = depth
		
		element = node.original_element
		
		# Build element line
		if node.is_interactive:
			# Interactive element with index
			new_prefix = '*' if node.is_new else ''
			line = f'{depth_str}{new_prefix}[{element.backend_node_id}]<{element.tag}'
		else:
			# Non-interactive container
			line = f'{depth_str}<{element.tag}'
		
		# Build attributes string
		attributes_html_str = DOMTreeSerializer._build_attributes_string(element, include_attributes)
		if attributes_html_str:
			line += f' {attributes_html_str}'
		
		# Add text content if available
		if element.text_content:
			line += f'>{cap_text_length(element.text_content, 100)}</{element.tag}>'
		elif element.label and element.label != element.text_content:
			# Use label as text content
			line += f'>{cap_text_length(element.label, 100)}</{element.tag}>'
		else:
			line += ' />'
		
		formatted_text.append(line)
		next_depth = depth + 1
		
		# Process children
		for child in node.children:
			child_text = DOMTreeSerializer.serialize_tree(child, include_attributes, next_depth)
			if child_text:
				formatted_text.append(child_text)
		
		return '\n'.join(formatted_text)
	
	@staticmethod
	def _build_attributes_string(element: InteractableElement, include_attributes: list[str]) -> str:
		"""Build the attributes string for an element."""
		attributes_to_include = {}
		
		# Include HTML attributes from element
		if element.attributes:
			for key, value in element.attributes.items():
				if key in include_attributes and value:
					attributes_to_include[key] = str(value).strip()
		
		# Add common attributes from element properties
		if element.id and 'id' in include_attributes:
			attributes_to_include['id'] = element.id
		if element.type and 'type' in include_attributes and element.tag.lower() in ['input', 'button']:
			attributes_to_include['type'] = element.type
		if element.placeholder and 'placeholder' in include_attributes:
			attributes_to_include['placeholder'] = element.placeholder
		if element.href and 'href' in include_attributes:
			attributes_to_include['href'] = element.href
		if element.role and 'role' in include_attributes:
			attributes_to_include['role'] = element.role
		if element.disabled and 'disabled' in include_attributes:
			attributes_to_include['disabled'] = 'true'
		
		# Add aria-label if label is different from text
		if element.label and element.label != element.text_content and 'aria-label' in include_attributes:
			attributes_to_include['aria-label'] = element.label
		
		if not attributes_to_include:
			return ''
		
		# Format attributes
		formatted_attrs = []
		for key, value in attributes_to_include.items():
			capped_value = cap_text_length(value, 100)
			if not capped_value:
				formatted_attrs.append(f"{key}=''")
			else:
				# Escape quotes in value
				safe_value = capped_value.replace('"', '&quot;').replace("'", "&#39;")
				formatted_attrs.append(f'{key}={safe_value}')
		
		return ' '.join(formatted_attrs)

