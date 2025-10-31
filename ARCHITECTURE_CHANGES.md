# Architecture Refactoring: Pure LLM Decision Making

## Overview
Refactored the autonomous web agent to use **100% LLM-based decision making** with **ZERO heuristics**.

## Changes Made

### 1. **Action Selection (`decide_action_node`)** ✅
**Before:** 
- Auto-selected scroll when max_score < 5.0
- Overrode LLM choices when score < 4.5
- Filtered candidates with complex heuristic rules
- Multiple safety checks and score thresholds

**After:**
- Pure LLM decision making
- LLM chooses from all scored candidates
- No score thresholds or overrides
- LLM balances exploration vs exploitation naturally
- Increased candidate list from 12 to 15 for better LLM visibility

**Key Change:**
```python
# OLD: Heuristic override
if max_score < 5.0 and scroll_candidate and len(recent_scrolls) == 0:
    return { 'next_action': scroll_candidate }

# NEW: Pure LLM decision
# LLM decides whether to scroll based on strategic reasoning
```

---

### 2. **Goal Evaluation (`check_goal_node`)** ✅
**Before:**
- Hardcoded heuristics for "commenting" goals
- Hardcoded heuristics for "Notion page creation"
- Pattern matching on action types and labels

**After:**
- Pure LLM evaluation of action sequences
- LLM analyzes complete action history (10 recent actions)
- Includes typed text in evaluation for verification
- Returns confidence score and missing steps

**Key Change:**
```python
# OLD: Heuristic checking
if "comment" in goal_text:
    if saw_type_into_comment and saw_click_comment:
        return {'goal_reached': True}

# NEW: Pure LLM evaluation
# LLM evaluates complete action sequence against goal
```

---

### 3. **Driver Hints Removed (`playwright_driver.py`)** ✅
**Before:**
- Pattern-matched button text for hints (create|new|filter|add)
- Special-case handling for UberEats (47 lines of heuristics)
- Surfaced hints to LLM as guidance

**After:**
- No hint extraction
- No special-case handling for any app
- Driver only provides raw page state (URL, elements, errors)
- LLM discovers patterns naturally

**Key Change:**
```python
# OLD: Heuristic hint extraction
hint = _page.evaluate("""
  () => {
    const btns = Array.from(document.querySelectorAll('button'))
               .map(b => b.innerText.toLowerCase());
    return btns.find(t => /create|new|filter|add/.test(t)) || '';
  }
""")

# NEW: No hints
hint = ''  # LLM makes all decisions
```

---

### 4. **State Cleanup** ✅
- Removed `driver_hint` from observe node updates
- Removed hint checking in score_actions_node
- Simplified state updates to only include necessary data

---

## Architecture Principles

### Pure LLM-Driven Design
1. **No hardcoded patterns** - LLM learns from context
2. **No score thresholds** - LLM evaluates quality naturally
3. **No special cases** - One unified decision process
4. **No override logic** - Trust LLM's strategic reasoning

### Heuristic Reasoning → LLM Prompts
**Critical**: The PURPOSE of removed heuristics was captured in enhanced LLM prompts:
- Heuristic: "Auto-scroll when score < 5.0" → Prompt: "EXPLORATION strategy - prefer scroll when all scores < 5.0"
- Heuristic: "Comment detection pattern" → Prompt: "COMMENTING GOALS pattern recognition"
- Heuristic: "Notion page creation pattern" → Prompt: "PAGE/NOTE CREATION pattern with title + body"
- Heuristic: "Button pattern matching (create|new|filter)" → Prompt: "ACTION TRIGGER BUTTONS strategy"

**Result**: LLM now understands WHY to look for patterns, not just THAT patterns exist

### What the LLM Now Controls
- ✅ Action scoring (already was LLM)
- ✅ Action selection (now pure LLM, was heuristic-mixed)
- ✅ Goal evaluation (now pure LLM, was heuristic-mixed)
- ✅ Exploration vs exploitation balance
- ✅ Error handling strategy
- ✅ When to scroll, click, type

### What Remains Non-LLM
- Driver primitives (click, type, scroll execution)
- Error detection (still captures UI errors for LLM)
- Loop prevention (tried_actions_by_url tracking)
- Max steps limit (safety mechanism)

---

## Prompt Enhancements: Heuristic Wisdom → LLM Context

### 1. Action Selection Prompt (`decide_action_node`)
**Added 5-point decision strategy:**
- **EXPLOITATION**: When/why to use high-scored actions (≥7.0)
- **EXPLORATION**: When/why to prefer scroll (<5.0 scores means explore)
- **ERROR RECOVERY**: How to prioritize fixing validation errors
- **AVOID LOOPS**: How to detect and break repetitive patterns
- **QUALITY AWARENESS**: How to be honest about poor candidates

**Concrete examples included:**
- "Top score 9.5 'Create project' → Click it" (exploitation)
- "Top score 4.2, scroll available → Scroll" (exploration)
- "Top score 7.5 but tried 2x → Try 2nd-best or scroll" (loop avoidance)

### 2. Goal Evaluation Prompt (`check_goal_node`)
**Added 7 goal pattern types with success criteria:**
1. **Commenting goals**: type into comment box → click submit
2. **Page/note creation**: type title field → type body field
3. **Project/item creation**: click create → fill fields → submit
4. **Filter/navigation**: navigate → apply filter
5. **Status changes**: click item → click status → select option
6. **General criteria**: completeness, error checking, evidence verification
7. **Confidence levels**: 0.0-1.0 scale with meanings

**Specific examples:**
- "typed 'hi' + clicked 'Comment' = SUCCESS"
- "typed title + typed body = PAGE CREATED"

### 3. Action Scoring Prompt (`score_actions_node`)
**Added 7-point scoring strategy:**
1. **Action trigger buttons**: Why "Create/New/Add" buttons score 9-10
2. **Submission buttons**: Why "Save/Submit/Confirm" finalize workflows
3. **Input fields**: How to match fields to goal (title vs body distinction)
4. **Semantic matching**: How to align labels with goal keywords
5. **Scroll for discovery**: When/why to propose scroll (score 6-7)
6. **Avoid repetition**: How to check action history
7. **Extract goal data**: How to parse multi-part goals (title + content)

**Specific guidance:**
- "If goal says 'create page X with content Y', extract BOTH X and Y"
- "Distinguish title fields ('Name') from body fields ('Description')"
- "If no high-quality candidates visible, propose scroll for discovery"

---

## Benefits

### 1. **Generalization**
- No app-specific code paths
- Works for ANY web app without custom logic
- LLM adapts to new UIs naturally

### 2. **Simplicity**
- Removed ~150 lines of heuristic code
- Cleaner, more maintainable codebase
- Easier to debug (one decision path)

### 3. **Flexibility**
- LLM can make nuanced decisions
- Adapts to edge cases without coding
- Strategic reasoning over rigid rules

### 4. **Transparency**
- All decisions explained by LLM rationale
- No hidden heuristic logic
- Clear reasoning chain

---

## Example Decision Flow

### Before (Heuristic-Heavy):
```
1. LLM scores actions
2. Check if max_score < 5.0 → force scroll
3. Check if score < 4.5 → override with scroll
4. Filter out "nonsensical" candidates
5. LLM picks from filtered list
6. Safety checks override LLM again
```

### After (Pure LLM):
```
1. LLM scores actions
2. LLM picks best action strategically
   - Considers scores, history, errors
   - Balances exploration vs exploitation
   - Makes strategic trade-offs
3. Execute LLM's choice
```

---

## Testing Recommendations

Test with diverse goals to verify LLM handles:
- ✅ Low-quality candidates (will LLM choose scroll?)
- ✅ Complex multi-step workflows
- ✅ Error recovery
- ✅ Different apps without special cases

---

## Files Modified

1. `src/agents/nodes.py`
   - `decide_action_node()` - Pure LLM decision
   - `check_goal_node()` - Pure LLM evaluation
   - `observe_node()` - Removed driver_hint
   - `score_actions_node()` - Removed hint usage

2. `src/drivers/playwright_driver.py`
   - Removed hint extraction
   - Removed UberEats special case
   - Simplified action execution

---

## Migration Notes

**No breaking changes to:**
- State structure (backward compatible)
- Workflow graph
- API contracts
- Driver interface

**Changed behavior:**
- More autonomous decision making
- Better generalization
- May take different action sequences (but should reach same goals)

