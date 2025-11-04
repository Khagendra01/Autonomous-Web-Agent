# Interactable Elements Usage Analysis

## Overview
This document tracks how many interactable elements are used at each stage of the agent workflow.

## 1. **Observe Node** (`src/agents/nodes/observe.py`)
- **Total Interactables Extracted**: All interactables found on the page (no limit)
- **Stored in State**: 
  - `interactable_elements`: First **200** elements kept for backward compatibility
  - `dom_state_llm_text`: Converted to browser-use format with **max_elements=200**
  - `selector_map`: Maps all indexed elements (up to 200)

**Code Reference:**
```python
dom_state = convert_interactables_to_dom_state(all_interactables, max_elements=200)
'interactable_elements': all_interactables[:200],  # Keep for backward compat
```

## 2. **Score Actions Node** (`src/agents/nodes/scoring.py`)
- **Default Max Elements**: **80** (configurable via `scoring_max_elements` in state)
- **Format Used**: 
  - If `dom_state_llm_text` exists: Uses browser-use format (first 8000 characters)
  - Fallback: Uses legacy format with first **80** interactables

**Code Reference:**
```python
max_elements = int(state.get('scoring_max_elements') or 80)
# Browser-use format: dom_state_text[:8000]  (character limit, not element count)
# Legacy format: interactables_full[:max_elements]  # 80 elements
```

## 3. **Decide Action Node** (`src/agents/nodes/decision.py`)
- **Input**: Uses `scored_actions` from scoring node (already filtered)
- **Candidates for LLM**: Top **8** scored actions after filtering
- **Filtering Applied**:
  - Removes actions already tried on current URL
  - Removes actions tried in last 10 steps globally
  - Removes recently filled fields (last 2 steps)

**Code Reference:**
```python
candidates_for_llm = available_actions[:8]  # Top 8 candidates
```

## 4. **Evaluate/Check Goal Node** (`src/agents/nodes/evaluate.py`)
- **Interactables Used**: All interactables from state (for summary)
- **Purpose**: Used to generate a summary of UI state, not for scoring

**Code Reference:**
```python
interactables = state.get('interactable_elements', [])
# Used for summary only, not for action selection
```

## Summary Table

| Stage | Max Interactables | Format | Purpose |
|-------|------------------|--------|---------|
| **Observe** | 200 | Browser-use format | Extract all clickable elements |
| **Scoring** | 80 (default) | Browser-use (8000 chars) or Legacy (80 elements) | Score actions for goal achievement |
| **Decision** | 8 (top candidates) | Already scored actions | Choose best action from top candidates |
| **Evaluate** | All (summary) | Legacy format | Check if goal is reached |

## Key Findings

1. **Observe Node**: Captures up to **200** interactable elements
2. **Scoring Node**: Uses **80** interactables (or first 8000 chars of browser-use format)
3. **Decision Node**: Considers top **8** scored actions
4. **Filtering**: Decision node filters out:
   - Actions tried on current URL
   - Actions tried in last 10 steps globally
   - Recently filled fields (last 2 steps)

## Configuration

To change the number of interactables used for scoring:
- Set `scoring_max_elements` in the initial state
- Default is 80 if not specified

Example:
```python
initial_state = {
    ...
    'scoring_max_elements': 100,  # Use 100 instead of 80
    ...
}
```

