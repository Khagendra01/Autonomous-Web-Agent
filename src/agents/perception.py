from .utils.vision import phash_bytes, visual_change, THRESHOLD
from .utils.dom import summarize_accessibility_tree, dom_fingerprint
from .state import AgentState, CapturedState, Interactable
from .knowledge import UIKB
from typing import Dict, Any


class Perception:
    def __init__(self):
        self.last_visual: str | None = None
        self.last_dom: str | None = None

    def categorize(self, obs: dict) -> str:
        roles = [(x.get('role'), (x.get('label') or '').lower()) for x in obs.get('interactables', [])]
        if any(r == "dialog" for r, _ in roles):
            return "create_modal_open"
        if any(r == "toast" for r, _ in roles):
            return "entity_created_success"
        if any(r == "textbox" for r, _ in roles):
            return "form_ready"
        return "state"

    def detect_and_capture(self, state: AgentState, obs: Dict[str, Any], image_bytes: bytes, storage) -> CapturedState | None:
        a11y = obs.get('a11y', {})
        a11y_str = summarize_accessibility_tree(a11y)
        dom_fp = dom_fingerprint(a11y_str)
        vhash = phash_bytes(image_bytes)

        significant = False
        if self.last_visual is None or self.last_dom is None:
            significant = True
        else:
            dv = visual_change(self.last_visual, vhash)
            significant = dv >= THRESHOLD or dom_fp != self.last_dom

        if not significant:
            return None

        self.last_visual, self.last_dom = vhash, dom_fp

        idx = len(state.memory.states) + 1
        shot_name = f"{idx:03d}.png"
        shot_path = storage.save_screenshot(image_bytes, shot_name)

        label = self.categorize(obs)
        interactables = [Interactable(**i) for i in obs.get('interactables', [])]
        cap = CapturedState(
            id=f"{idx:03d}",
            label=label,
            url=obs.get('url'),
            dom_fingerprint=dom_fp,
            visual_hash=vhash,
            screenshot_path=shot_path,
            interactables=interactables,
            action_leading_here=state.last_action,
        )
        state.memory.states.append(cap)
        state.memory.seen_fingerprints.append(dom_fp)
        # Convert to dict with datetime serialization
        storage.append_state(cap.model_dump(mode='json'))

        # Learn newly seen labeled buttons as potential semantics
        kb = UIKB(state.app)
        learns = []
        for i in obs.get('interactables', []):
            lab = (i.get('label') or '').lower()
            if 'create' in lab or lab.strip() == '+':
                learns.append({'label': i.get('label'), 'role': i.get('role'), 'selector': i.get('selector'), 'semantic': ['create']})
            if 'filter' in lab:
                learns.append({'label': i.get('label'), 'role': i.get('role'), 'selector': i.get('selector'), 'semantic': ['filter']})
            if lab in {'create', 'save', 'done', 'submit'}:
                learns.append({'label': i.get('label'), 'role': i.get('role'), 'selector': i.get('selector'), 'semantic': ['submit']})
        if learns:
            kb.learn(learns)

        return cap

