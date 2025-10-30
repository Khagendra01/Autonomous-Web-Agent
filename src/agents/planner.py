from typing import Dict, Any, List
from .state import AgentState
from .knowledge import UIKB
from .vision_hook import infer_semantics_from_screen


GOAL_SEMANTICS = {
    'create': ['create', '+', 'new', 'add'],
    'filter': ['filter'],
    'submit': ['submit', 'create', 'save', 'done']
}


class Planner:
    def __init__(self):
        self.kb_cache = {}

    def kb(self, app: str) -> UIKB:
        if app not in self.kb_cache:
            self.kb_cache[app] = UIKB(app)
        return self.kb_cache[app]

    def _goal_to_sem(self, goal: str) -> List[str]:
        g = goal.lower()
        wants: List[str] = []
        if 'create' in g:
            wants.append('create')
        if 'filter' in g:
            wants.append('filter')
        if 'submit' in g or 'save' in g:
            wants.append('submit')
        return wants or ['explore']

    def choose_from(self, acts: List[Dict[str, Any]], sem_wanted: List[str]) -> Dict[str, Any] | None:
        # prefer explicit role/button with desired semantics inferred from label
        for s in sem_wanted:
            for a in acts:
                if a.get('role') == 'button':
                    label = (a.get('label') or '').lower()
                    if any(tok in label for tok in GOAL_SEMANTICS.get(s, [])):
                        return {'type': 'click', 'selector': a.get('selector'), 'intent': f'{s}_via_dom'}
        return None

    def plan_next(self, state: AgentState, screenshot: bytes | None = None) -> Dict[str, Any]:
        obs = state.observation or {}
        acts = obs.get('interactables', [])
        wants = self._goal_to_sem(state.goal)
        kb = self.kb(state.app)

        # 1) Use KB first
        for s in wants:
            known = kb.query(s)
            if known:
                sel = next((k.get('selector') for k in known if k.get('selector')), None)
                if sel:
                    return {'type': 'click', 'selector': sel, 'intent': f'{s}_via_kb'}

        # 2) DOM-first inference
        pick = self.choose_from(acts, wants)
        if pick:
            learned = [{
                'label': a.get('label'), 'role': a.get('role'), 'selector': a.get('selector'), 'semantic': wants
            } for a in acts if a.get('selector') == pick.get('selector')]
            if learned:
                kb.learn(learned)
            return pick

        # 3) Vision fallback (only if screenshot provided)
        if screenshot:
            inferred = infer_semantics_from_screen(screenshot, acts)
            if inferred:
                kb.learn(inferred)
                for s in wants:
                    known = kb.query(s)
                    if known:
                        sel = next((k.get('selector') for k in known if k.get('selector')), None)
                        if sel:
                            return {'type': 'click', 'selector': sel, 'intent': f'{s}_via_vision'}

        # 4) Exploration
        return {'type': 'scroll', 'delta': 700, 'intent': 'explore'}

