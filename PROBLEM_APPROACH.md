## Problem → Approach: Dynamic, App-Agnostic Form Completion

### The Problem (observed behavior)
- After clicking a context-opening control (e.g., “Create new issue”), the agent sometimes immediately clicks the submit button instead of filling inputs.
- Evaluation prematurely declared success after a single click, ending the loop without typing.
- Root causes from logs:
  - Inputs were not present in the scorer’s view (pruned/timing), so no type candidates existed.
  - Form readiness wasn’t detected; submit demotion didn’t engage.
  - Evaluation’s auto-complete heuristic ended the run post-click.

### Design Principles
- Purely dynamic and app-agnostic: rely on roles/affordances (role="textbox", "searchbox", "combobox", contenteditable) and generic signals, not product-specific schemas.
- Evidence-before-commit: reduce uncertainty (type/select in-form) before attempting submit/confirm.
- Minimal LLM surface: deterministic pre-ranking + tiny re-ranker; short-circuit on clear wins.

### Approach Overview
1) Observe: preserve input affordances
   - Compute “form-ready” using the full interactables set: presence of any textbox/searchbox/contenteditable/combobox ⇒ form_ready.
   - Reserve a small quota of input elements in the pruned set so scoring can always see at least some inputs.

2) Scoring: context-driven candidate synthesis and gating
   - When form_ready and no recent in-form progress:
     - Synthesize generic type candidates for visible inputs with neutral text (summarized instruction).
     - Synthesize open/select paths for comboboxes if needed (open now; select on next step).
     - Temporarily demote submit/confirm until at least one in-form action (type/select) occurs.
   - Short-circuit when a single high-confidence in-form action exists and alternatives are clearly weaker.

3) Execute: let the UI render
   - After context-opening clicks (create/new/open/edit), issue a brief await before the next observe so inputs render.
   - Track generic `form_progress` (count of type/select actions) to lift submit demotion and signal evaluation.

4) Evaluate: outcome over clicks
   - Remove premature auto-complete: never conclude immediately after a context-opening click.
   - Require either in-form action(s) (form_progress > 0) or a persisted success signal (detail URL/confirmation text).
   - Consider current top‑K as “remaining actions”; if any ≥ threshold remain, do not complete.

### Why this works across apps
- It keys off universal affordances (roles, contenteditable, basic attributes), not task-specific fields.
- It prioritizes uncertainty reduction (typing/selecting) whenever a form is present.
- It avoids early submission without requiring product-specific logic.

### Success Criteria
- After opening a form: observe inputs, synthesize type candidates, select a type action, then submit.
- Evaluation declares success only after in-form actions or persisted signals.
- The same pipeline handles “create issue,” “compose email,” “rename entity,” etc., because it is affordance- and context-driven.


