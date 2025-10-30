from typing import Dict, Any


class Executor:
    """Thin bridge to the Node/TS Playwright driver via local HTTP.
    Assumes a local HTTP server started by the driver (localhost:3999).
    """

    def __init__(self, base_url: str = 'http://127.0.0.1:3999'):
        self.base = base_url

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import requests
        r = requests.post(self.base + path, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()

    def init(self, app: str, cookies_path: str) -> Dict[str, Any]:
        return self._post('/init', {'app': app, 'cookiesPath': cookies_path})

    def observe(self) -> Dict[str, Any]:
        return self._post('/observe', {})

    def screenshot(self) -> bytes:
        import requests
        r = requests.get(self.base + '/screenshot', timeout=60)
        r.raise_for_status()
        return r.content

    def act(self, action: Dict[str, Any]) -> Dict[str, Any]:
        return self._post('/act', action)

