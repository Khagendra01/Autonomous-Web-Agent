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
            lab = (i.get('label') or '').lower().strip()
            semantics = []
            
            # Detect create/add actions
            if any(word in lab for word in ['create', 'add', 'new', '+']) or lab == '+':
                semantics.append('create')
            
            # Detect filter actions
            if 'filter' in lab:
                semantics.append('filter')
            
            # Detect submit/save actions
            if any(word in lab for word in ['save', 'submit', 'done', 'finish', 'confirm', 'ok']):
                semantics.append('submit')
            
            # Detect delete/remove actions
            if any(word in lab for word in ['delete', 'remove', 'trash', 'cancel']):
                semantics.append('delete')
            
            # Detect edit actions
            if any(word in lab for word in ['edit', 'update', 'modify', 'change']):
                semantics.append('edit')
            
            # Detect search actions
            if any(word in lab for word in ['search', 'find']):
                semantics.append('search')
            
            # Only learn if we detected semantic meaning
            if semantics:
                learns.append({
                    'label': i.get('label'),
                    'role': i.get('role'),
                    'selector': i.get('selector'),
                    'semantic': semantics
                })
        
        if learns:
            kb.learn(learns)
            print(f"  🧠 Learned {len(learns)} UI pattern(s)")

        return cap

