from typing import Dict, Any
import json

VISIBLE_KEYS = {'role', 'name', 'checked', 'disabled', 'value'}


def summarize_accessibility_tree(a11y_snapshot: Dict[str, Any]) -> str:
    # Keep a compact JSON string of relevant nodes
    def prune(node):
        keep = {k: v for k, v in node.items() if k in VISIBLE_KEYS}
        kids = [prune(c) for c in node.get('children', []) if c.get('role') not in {'none'}]
        if kids:
            keep['children'] = kids
        return keep

    pruned = prune(a11y_snapshot)
    return json.dumps(pruned, separators=(',', ':'))


def dom_fingerprint(a11y_str: str) -> str:
    # simple stable hash
    import hashlib
    return hashlib.sha1(a11y_str.encode('utf-8')).hexdigest()[:16]

