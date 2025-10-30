# 🎯 Simplified Autonomous Web Agent

This is a **minimal, easy-to-understand** version of the autonomous web agent.

## What Changed?

### Before (Complex) ❌
- **636 lines** in `planner.py` with lots of special cases
- Manual button scoring and relevance calculation
- YouTube-specific logic, form detection heuristics
- Knowledge base integration
- Loop detection and failure recovery
- Complex prompt engineering

### After (Simple) ✅
- **~120 lines** in `planner_simple.py`
- Let LLM do all the reasoning
- No special cases or heuristics
- Clean, readable code
- Easy to extend

## Architecture

### Core Loop (4 Steps)

```
1. OBSERVE → Capture page state (URL, elements, screenshot)
2. PLAN    → LLM decides what action to take
3. ACT     → Execute the action (click, type, scroll)
4. CHECK   → LLM validates if goal is complete
```

### Files

```
src/agents/
  planner_simple.py  # Simple LLM-based planner (~120 lines)
  graph_simple.py    # Simple workflow graph (~150 lines)
  state.py           # State models (unchanged)
  executor.py        # HTTP client for browser (unchanged)
  perception.py      # Screenshot capture (unchanged)
```

## How to Use

### Run the Simplified Agent

```bash
# Terminal 1: Start the browser driver
python -m src.drivers.playwright_driver

# Terminal 2: Run the simplified agent
python -m src.agents.graph_simple run "create a project in linear named test"
```

### Customize Max Steps

```bash
python -m src.agents.graph_simple run "complex task" --max-steps 50
```

## Code Walkthrough

### 1. Simple Planner (`planner_simple.py`)

**Three simple methods:**

```python
class SimplePlanner:
    def extract_app_and_url(goal) -> dict:
        """Ask LLM: What app and URL for this goal?"""
        # Returns: {'app': 'linear', 'url': 'https://linear.app/'}
    
    def plan_next_action(state) -> AgentState:
        """Ask LLM: What action should I take next?"""
        # Shows LLM the goal + available elements
        # LLM returns: click/type/scroll action
    
    def check_completion(state) -> AgentState:
        """Ask LLM: Is the goal complete?"""
        # LLM checks if we're done
```

**Key Simplifications:**
- No manual scoring - LLM sees all elements and chooses
- No special cases - LLM handles YouTube, forms, etc. naturally
- No heuristics - Pure LLM reasoning

### 2. Simple Graph (`graph_simple.py`)

**Four clean nodes:**

```python
def observe_node(state):
    """Get page state and screenshot"""
    obs = executor.observe()
    img = executor.screenshot()
    return state

def plan_node(state):
    """LLM plans next action"""
    state = planner.plan_next_action(state)
    return state

def act_node(state):
    """Execute the action"""
    executor.act(action)
    return state

def check_node(state):
    """LLM checks completion"""
    state = planner.check_completion(state)
    return state
```

**Workflow:**
```
observe → plan → act → check → (loop or end)
```

## Why This is Better

### ✅ Pros
1. **Readable**: Anyone can understand the code in 10 minutes
2. **Maintainable**: Easy to modify and extend
3. **Debuggable**: Simple flow, easy to trace
4. **Flexible**: LLM handles edge cases naturally
5. **Shorter**: ~270 lines vs ~636 lines in planner alone

### ⚠️ Trade-offs
1. **Token usage**: More LLM calls = more tokens (but GPT-4o is cheap)
2. **Less optimization**: No button pre-scoring (but LLM is smart enough)
3. **Slower**: Slightly slower without heuristics (but cleaner)

## Next Steps: How to Extend

### Add Error Recovery
```python
def plan_next_action(state):
    # Check for repeated failures
    if state.consecutive_failures >= 3:
        prompt += "\n⚠️ Try a different approach!"
    ...
```

### Add Domain Knowledge
```python
def plan_next_action(state):
    # Add app-specific hints
    if state.app == 'linear':
        prompt += "\nHint: Use the 'New Project' button"
    ...
```

### Add Vision
```python
def plan_next_action(state):
    # Send screenshot to GPT-4o Vision
    image_data = base64.b64encode(state.screenshot)
    messages.append(ImageMessage(image=image_data))
    ...
```

## Comparison

| Feature | Original | Simplified |
|---------|----------|------------|
| Lines of code (planner) | 636 | ~120 |
| Special cases | Many | None |
| Button scoring | Manual heuristics | LLM decides |
| Loop detection | Custom logic | Can add if needed |
| Knowledge base | Integrated | Optional |
| Prompt complexity | High | Low |
| Readability | Medium | High |
| Maintainability | Medium | High |

## When to Use Which?

### Use Simplified Version When:
- Learning how the agent works
- Prototyping new features
- Building a new agent from scratch
- Prefer code clarity over optimization
- Don't need every edge case handled

### Use Original Version When:
- Need maximum performance
- Have specific domain knowledge to encode
- Need sophisticated error recovery
- Require loop detection and failure handling
- Production system with known edge cases

## Getting Started

1. **Read the code**: Start with `planner_simple.py` (only 120 lines!)
2. **Run an example**: Try the Linear project creation task
3. **Modify the prompts**: Experiment with different instructions
4. **Add your own features**: Extend incrementally

## Philosophy

> **"Make it work, make it right, make it fast"**
> — Kent Beck

This simplified version focuses on **"make it work"** and **"make it right"**.  
The original version adds **"make it fast"** with optimizations.

Start simple, add complexity only when needed.

---

**Questions?** Read the code - it's self-documenting! 🚀

