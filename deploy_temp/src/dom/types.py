"""Type definitions for DOM serialization."""
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class NodeType(int, Enum):
	"""DOM node types."""
	ELEMENT_NODE = 1
	TEXT_NODE = 3
	DOCUMENT_NODE = 9
	DOCUMENT_FRAGMENT_NODE = 11


@dataclass
class DOMRect:
	"""Bounding box rectangle."""
	x: float
	y: float
	width: float
	height: float


@dataclass
class InteractableElement:
	"""Represents an interactable element from gRPC."""
	role: str
	label: str
	selector: str
	disabled: bool
	tag: str
	classes: list[str]
	id: str
	href: str
	type: str
	placeholder: str
	# Additional fields for browser-use format
	attributes: dict[str, str] = field(default_factory=dict)
	text_content: str = ""
	llm_index: int = 0  # Index for LLM to reference (enumeration index)
	backend_node_id: int = 0  # Real CDP backend_node_id (0 if unavailable, will be resolved at execution time)


@dataclass
class SimplifiedNode:
	"""Simplified tree node for optimization."""
	original_element: InteractableElement
	children: list['SimplifiedNode'] = field(default_factory=list)
	should_display: bool = True
	is_interactive: bool = False
	is_new: bool = False
	excluded_by_parent: bool = False
	depth: int = 0


# Map from backend_node_id (index) to InteractableElement
SelectorMap = dict[int, InteractableElement]


@dataclass
class SerializedDOMState:
	"""Serialized DOM state for LLM consumption."""
	_root: Optional[SimplifiedNode]
	selector_map: SelectorMap
	
	def llm_representation(self, include_attributes: Optional[list[str]] = None) -> str:
		"""Generate LLM-friendly string representation."""
		from .serializer import DOMTreeSerializer
		
		if not self._root:
			return 'Empty DOM tree (you might have to wait for the page to load)'
		
		include_attributes = include_attributes or DEFAULT_INCLUDE_ATTRIBUTES
		return DOMTreeSerializer.serialize_tree(self._root, include_attributes)


DEFAULT_INCLUDE_ATTRIBUTES = [
	'title', 'type', 'checked', 'id', 'name', 'role', 'value',
	'placeholder', 'alt', 'aria-label', 'aria-expanded',
	'data-state', 'aria-checked', 'pattern', 'min', 'max',
	'minlength', 'maxlength', 'step', 'accept', 'multiple',
	'inputmode', 'autocomplete', 'href', 'disabled', 'required',
]

