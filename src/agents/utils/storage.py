from pathlib import Path
import json, time
from typing import Dict, Any


class RunStorage:
    def __init__(self, base_dir: str, app: str, task_slug: str):
        ts = time.strftime('%Y-%m-%dT%H-%M-%SZ', time.gmtime())
        self.root = Path(base_dir) / app / task_slug / ts
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'screens').mkdir(exist_ok=True)
        self.manifest = {
            'app': app,
            'task': task_slug,
            'timestamp': ts,
            'states': []
        }

    def save_screenshot(self, image_bytes: bytes, name: str) -> str:
        p = self.root / 'screens' / name
        p.write_bytes(image_bytes)
        return str(p)

    def append_state(self, state: Dict[str, Any]):
        self.manifest['states'].append(state)

    def flush(self):
        (self.root / 'index.json').write_text(json.dumps(self.manifest, indent=2))

