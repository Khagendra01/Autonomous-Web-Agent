from __future__ import annotations
from typing import Dict, Any, List
from pathlib import Path
import json


KB_DIR = Path('knowledge')
KB_DIR.mkdir(exist_ok=True)


class UIKB:
    def __init__(self, app: str):
        self.app = app
        self.path = KB_DIR / f"{app}.ui.json"
        self.data = {"app": app, "interactables": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                pass

    def save(self):
        tmp = self.path.with_suffix('.ui.json.tmp')
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)

    def query(self, semantic: str) -> List[Dict[str, Any]]:
        return [i for i in self.data.get('interactables', []) if semantic in i.get('semantic', [])]

    def learn(self, items: List[Dict[str, Any]]):
        # merge new items by (role,label,selector)
        def key(x):
            return (x.get('role'), (x.get('label') or '').strip(), (x.get('selector') or '').strip())

        old = {key(i): i for i in self.data.get('interactables', [])}
        for it in items:
            k = key(it)
            if k in old:
                sem = set(old[k].get('semantic', [])) | set(it.get('semantic', []))
                old[k]['semantic'] = sorted(sem)
            else:
                old[k] = it
        self.data['interactables'] = list(old.values())
        self.save()

