# Code Inefficiencies Analysis

## Critical Performance Issues

### 1. **Excessive I/O Operations - Logging with fsync()**
**Location:** `src/agents/utils/logger.py:36`
```python
os.fsync(self.log_file.fileno())  # Force write to disk
```
**Impact:** HIGH - Forces disk sync on EVERY log write. This is extremely expensive (can take 10-100ms per write).
**Fix:** Remove `os.fsync()` or only call it periodically (every N logs or at critical points).

### 2. **Duplicate JSON Extraction Functions**
**Locations:**
- `src/agents/nodes/decision.py:25` - `_extract_json_payload()`
- `src/agents/nodes/evaluate.py:9` - `_extract_json_payload()`
- `src/agents/nodes/scoring.py:17` - `_extract_json_array()` (similar logic)

**Impact:** MEDIUM - Code duplication, maintenance burden, potential bugs from inconsistent implementations.
**Fix:** Create shared utility function in `src/agents/utils/json_parser.py` or similar.

### 3. **Multiple LLM API Calls Per Step**
**Workflow:** Every step makes 3 separate LLM calls:
1. Scoring (score_actions_node) - rates all actions
2. Decision (decide_action_node) - chooses from scored actions
3. Evaluation (check_goal_node) - checks if goal reached

**Impact:** VERY HIGH - Cost and latency multiply. Each call:
- Scoring: ~$0.03-0.10 per call (80-200 elements)
- Decision: ~$0.01-0.03 per call
- Evaluation: ~$0.01-0.03 per call
**Total per step: ~$0.05-0.16**

**Potential Optimization:**
- Combine scoring and decision into single call with structured output
- Cache evaluation results (only check every N steps or when action suggests completion)
- Use smaller context windows (summarize instead of full JSON)

### 4. **Redundant Screenshot Operations**
**Locations:**
- `src/agents/nodes/observe.py:20` - Takes full screenshot every step
- `src/agents/nodes/execute.py:50` - Takes focused screenshot before action

**Impact:** MEDIUM - Screenshots are expensive (network I/O, image encoding). Taking full page + focused region every step is wasteful.
**Fix:**
- Only take focused screenshot if action actually succeeds
- Skip full screenshot if URL hasn't changed and recent screenshot exists
- Cache screenshots for short duration

### 5. **Inefficient String Operations**
**Pattern Found:** Multiple `.lower()` calls on same strings throughout:
- `decision.py:76-101` - Repeated `.lower()` on `label`, `placeholder`, etc.
- `scoring.py:231-256` - Same pattern

**Impact:** LOW-MEDIUM - Small performance hit, but adds up with large lists.
**Fix:** Cache lowercased strings in data structures.

### 6. **Large Prompt Sizes**
**Location:** All LLM nodes send full JSON of interactables
**Example:** `scoring.py:493` sends full `json.dumps(interactables, indent=2)`
- With 80 elements, this can be 50-100KB of JSON per call
- Each element has ~10-15 fields

**Impact:** HIGH - Larger prompts = more tokens = more cost + slower
**Fix:**
- Send summaries instead of full JSON
- Use embeddings to compress element descriptions
- Only send top N elements by relevance score

### 7. **Redundant List Comprehensions**
**Location:** `decision.py:62-272` - `_build_dynamic_decision_context()`
**Example:**
```python
# Lines 109-114: Filter candidates
all_newly_appeared_option_candidates = [
    c for c in candidates
    if c.get('action_type') == 'click' and
    'role=option' in c.get('selector', '') and
    c.get('selector', '') not in prev_selectors
]

# Lines 117-124: Another pass over same candidates
matching_candidates = [
    c for c in candidates
    if c.get('action_type') == 'click' and
    (typed_text in (c.get('label') or '').lower() or ...)
]
```

**Impact:** MEDIUM - Multiple passes over same data. With 15 candidates, this is minor, but pattern appears throughout.
**Fix:** Single pass that builds multiple filtered lists.

### 8. **Exception Handling Overhead**
**Location:** `execute.py:47-64`
**Issue:** Nested try-except with repeated code:
```python
try:
    if action.selector and action.action_type in ('click', 'type'):
        try:
            focused_bytes = driver_client.screenshot_region(...)
            screenshots = state.get('screenshots') or []
            screenshots = screenshots + [focused_bytes]
            focused_after_steps = set(state.get('focused_after_steps') or [])
            focused_after_steps.add(...)
        except Exception:
            screenshots = state.get('screenshots') or []  # Repeated
            focused_after_steps = set(state.get('focused_after_steps') or [])  # Repeated
    else:
        screenshots = state.get('screenshots') or []  # Repeated
        focused_after_steps = set(state.get('focused_after_steps') or [])  # Repeated
except Exception:
    screenshots = state.get('screenshots') or []  # Repeated AGAIN
    focused_after_steps = set(state.get('focused_after_steps') or [])  # Repeated AGAIN
```

**Impact:** LOW-MEDIUM - Code duplication, maintenance issue, potential bug if logic diverges.
**Fix:** Extract common initialization, use single try-except.

### 9. **Memory Inefficiency - Storing All Screenshots**
**Location:** `src/agents/state.py:36` - `screenshots: List[bytes]`
**Issue:** All screenshots kept in memory throughout execution. Each screenshot can be 500KB-2MB.
**Impact:** MEDIUM - Memory usage grows linearly with steps. 15 steps = 7.5-30MB just for screenshots.
**Fix:**
- Write screenshots to disk immediately
- Store file paths instead of bytes
- Clear old screenshots after saving

### 10. **Complex Combobox Logic Duplication**
**Locations:**
- `scoring.py:230-420` - ~190 lines of combobox detection logic
- `decision.py:85-243` - ~160 lines of similar combobox logic

**Impact:** MEDIUM - Code duplication, maintenance nightmare, potential inconsistencies.
**Fix:** Extract to shared utility function in `utils/combobox.py`.

### 11. **Inefficient State Updates**
**Pattern:** Creating new dictionaries for state updates instead of efficient merges
**Example:** `execute.py:141-148`
```python
return {
    'action_history': state['action_history'] + [action_record],  # Creates new list
    'step_count': state['step_count'] + 1,
    'stuck_count': 0,
    'tried_actions_by_url': tried_map,  # New dict
    'screenshots': screenshots,  # New list
    'focused_after_steps': list(focused_after_steps),  # New list
}
```

**Impact:** LOW - Python is efficient at this, but pattern suggests missed optimization opportunities.
**Note:** This is likely fine for LangGraph's state management, but worth monitoring.

### 12. **No Caching of Computed Values**
**Missing:**
- `prev_selectors` set is recomputed multiple times per step
- Lowercased strings recomputed
- Element filtering repeated with same criteria

**Impact:** LOW-MEDIUM - Small performance gains possible.
**Fix:** Cache computed values in state or use memoization for expensive operations.

### 13. **Redundant Driver Calls**
**Location:** `execute.py:98-117`
**Issue:** Post-action verification makes 2-4 additional driver calls:
- Assert text present (can fail)
- Press Enter (retry)
- Retype action (retry)
- Assert again

**Impact:** MEDIUM - Adds latency and potential for cascading failures.
**Fix:** 
- Make verification optional/configurable
- Use timeout/retry logic instead of multiple separate calls

## Recommended Priority Fixes

1. **CRITICAL:** Remove `os.fsync()` from logger (10-100x logging speed improvement)
2. **HIGH:** Optimize LLM calls - combine scoring+decision, cache evaluation
3. **HIGH:** Reduce prompt sizes - use summaries instead of full JSON
4. **MEDIUM:** Fix duplicate code - extract JSON parsing, combobox logic
5. **MEDIUM:** Optimize screenshot operations - cache, skip when unchanged
6. **MEDIUM:** Fix exception handling duplication in execute.py
7. **LOW:** Cache string operations and computed sets

## Estimated Impact

If all fixes applied:
- **Latency:** 30-50% reduction per step (mainly from LLM optimization)
- **Cost:** 40-60% reduction in LLM API costs
- **Memory:** 50-70% reduction (screenshot management)
- **Code maintainability:** Significantly improved

