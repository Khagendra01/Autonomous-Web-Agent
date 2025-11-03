"""Utility functions for DOM processing."""

def cap_text_length(text: str, max_length: int) -> str:
	"""Cap text length for display."""
	if not text:
		return ""
	if len(text) <= max_length:
		return text
	return text[:max_length] + '...'

