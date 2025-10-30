# 🐭 Flood Fill Agent - Autonomous Web Exploration

**Inspired by Micromouse maze-solving algorithm**, this agent autonomously explores web UIs, learns optimal paths, and reuses knowledge across runs.

---

## 🧠 Core Concept: State Space as a Maze

### The Micromouse Analogy

| Micromouse | Web Agent |
|------------|-----------|
| **Maze cells** | UI States (DOM snapshots) |
| **Walls** | Invalid/failed actions |
| **Distance values** | Steps to goal (flood fill) |
| **Goal cell (distance=0)** | Task completion state |
| **Robot** | Current page state |
| **Movement** | Actions (click, type, scroll) |
| **Exploration** | Trying new actions |

---

## 🎯 How It Works

### 1. **State Graph Building**
```
Every unique UI state gets a fingerprint:
  State A (home) → [transitions] → State B (projects) → State C (form)
```

### 2. **Flood Fill Distance Calculation**
```
Goal State (project created): distance = 0
Form State (ready to submit): distance = 1
Projects Page (form not open): distance = 2
Home Page: distance = 3

Agent always moves toward LOWEST distance neighbor!
```

### 3. **Exploration Strategy**

**Exploit (Use Known Paths):**
- If we've been here before and know a good action → Take it!
- Success rate > 50% → Follow the known path

**Explore (Try New Actions):**
- If no known path → Try unexplored actions
- Use LLM to pick most relevant action
- Build knowledge for future runs

### 4. **Knowledge Reuse**
```
Run 1: Explores blindly, learns the UI
  - Tries 20 actions
  - Finds optimal path (4 actions)
  - Saves to knowledge/graphs/linear_graph.json

Run 2: Uses learned knowledge
  - Loads graph with 15 states
  - Takes optimal path immediately
  - Completes in 4 actions! ✨
```

---

## 🚀 Usage

### Run the Flood Fill Agent

```bash
# Terminal 1: Start Playwright driver
python -m src.drivers.playwright_driver

# Terminal 2: Run flood fill agent
python -m src.agents.graph_flood_fill run "create a project in linear named alpha"
```

### What You'll See

```
🐭 FLOOD FILL Autonomous Agent
Goal: create a project in linear named alpha
============================================================

[FLOOD FILL] Loaded existing graph with 15 states

[OBSERVE] Step 0/50
  URL: https://linear.app/...
  Elements: 52

[FLOOD FILL] State: 7a3f2b... (visited 2x, distance=3.0)
[STRATEGY] EXPLOIT known path (success rate: 100%)
[PLAN] Following known good path: click:Projects
[ACT] Executing...
  ✓ Success

[OBSERVE] Step 1/50
[FLOOD FILL] State: 9d4e1c... (visited 1x, distance=2.0)
[STRATEGY] EXPLOIT known path (success rate: 100%)
...

✅ Task Complete!
Success: True
Steps: 4

📊 State Graph:
  States explored: 18
  Transitions learned: 42
  Goal states: 1
```

---

## 📁 File Structure

```
src/agents/
  state_graph.py         # Core state graph + flood fill
  planner_flood_fill.py  # Flood fill planning logic
  graph_flood_fill.py    # LangGraph workflow

knowledge/graphs/
  linear_graph.json      # Learned state graph for Linear
  github_graph.json      # Learned state graph for GitHub
  ...
```

---

## 🔍 How Decisions Are Made

### Example: "Create project named test"

**Step 1:** Agent starts on home page
```
Current State: home_page (distance=∞)
Available actions: Projects, Issues, Settings, ...

[EXPLORE] Never been here, trying new actions
LLM picks: "click Projects" (most relevant to goal)
```

**Step 2:** Now on projects page
```
Current State: projects_page (distance=∞)
Known transition: home_page → click Projects → projects_page ✓

[EXPLORE] New state, trying new actions
LLM picks: "click Add project" (form creation)
```

**Step 3:** Form modal opened
```
Current State: form_modal (distance=∞)
Textboxes detected!

[EXPLORE] Trying: type "test" in name field
```

**Step 4:** Form filled
```
Current State: form_filled (distance=∞)

[EXPLORE] Trying: click "Create" button
```

**Step 5:** Project created! 🎉
```
[GOAL] Achieved! Project successfully created
Setting this state as GOAL (distance=0)

Running flood fill...
  form_filled → distance = 1
  form_modal → distance = 2
  projects_page → distance = 3
  home_page → distance = 4

Graph saved to knowledge/graphs/linear_graph.json
```

**Next Run:** Agent loads graph, sees optimal path, takes it directly! ⚡

---

## 🎓 Key Advantages

### 1. **True Autonomy**
- Explores UI on its own
- No hardcoded workflows
- Adapts to changes automatically

### 2. **Learning & Memory**
- Every run improves the graph
- Failed actions marked as "walls"
- Success paths reinforced

### 3. **Optimal Paths**
- Flood fill guarantees shortest path
- Once learned, execution is instant
- Reusable across similar tasks

### 4. **Failure Recovery**
- Action fails? Mark as unreliable, try alternative
- New UI elements? Explore and add to graph
- Page changes? Graph adapts automatically

---

## 🔧 Advanced Features

### LLM-Based Components

1. **Goal Detection**
   - LLM checks if task is complete
   - Returns confidence score
   - Marks state as goal (distance=0)

2. **Distance Estimation**
   - LLM scores "closeness to goal" (0-1)
   - Helps when goal not reached yet
   - Guides exploration toward relevant areas

3. **Action Selection (Exploration)**
   - When no known path, LLM picks best action
   - Considers: element labels, goal, context
   - Builds knowledge for future runs

### Graph Statistics

```python
{
  'total_states': 18,
  'total_transitions': 42,
  'goal_states': 1,
  'most_visited': 5
}
```

---

## 🧪 Example Scenarios

### Scenario 1: First Run (Pure Exploration)
```
Goal: Create project "alpha"
Knowledge: Empty graph

Actions:
  Step 1: Try "Issues" → Dead end, mark as distance=∞
  Step 2: Try "Projects" → Promising, continue
  Step 3: Try "Settings" → Wrong direction
  Step 4: Back to "Projects", try "Add project"
  Step 5: Type in form
  Step 6: Submit → SUCCESS! Mark as goal

Result: 6 steps, graph saved with optimal path
```

### Scenario 2: Second Run (Knowledge Reuse)
```
Goal: Create project "beta"
Knowledge: Loaded graph with 18 states

Actions:
  Step 1: EXPLOIT: click "Projects" (known good, distance=3→2)
  Step 2: EXPLOIT: click "Add project" (known good, distance=2→1)
  Step 3: EXPLOIT: type "beta" in textbox (known good, distance=1→0)
  Step 4: EXPLOIT: click "Create" (known good, distance=0→GOAL)

Result: 4 steps (optimal path)! ⚡
```

### Scenario 3: UI Changed (Adaptation)
```
Goal: Create project "gamma"
Knowledge: Loaded graph, but "Add project" button moved

Actions:
  Step 1: EXPLOIT: click "Projects" ✓
  Step 2: EXPLOIT: click "Add project" ✗ (not found)
  Step 3: EXPLORE: Search for new create button
  Step 4: Found "New project" button, try it ✓
  Step 5: Update graph: Projects → "New project" → form
  ...

Result: Adapted to UI change, updated graph
```

---

## 🎯 Future Enhancements

- [ ] Visual state recognition (screenshots + vision models)
- [ ] Multi-goal planning (composite tasks)
- [ ] Transfer learning (reuse GitHub knowledge for GitLab)
- [ ] Collaborative graphs (share knowledge across users)
- [ ] Reinforcement learning (optimize exploration strategy)

---

## 💡 Philosophy

**"Don't program the agent, let it learn the UI."**

Instead of:
```python
# ❌ Hardcoded workflow
click("Projects")
click("Add project")
type("name", project_name)
click("Create")
```

We do:
```python
# ✅ Autonomous exploration
agent.explore(goal="create project")
# Agent figures it out and remembers for next time!
```

---

## 🏆 Comparison

| Feature | Simple Agent | Flood Fill Agent |
|---------|-------------|-----------------|
| **Knowledge** | None | Persistent graph |
| **Learning** | No | Yes, improves over time |
| **Optimal paths** | No | Yes, via flood fill |
| **Adaptability** | Manual fixes | Self-adapting |
| **Reusability** | Every run starts fresh | Reuses learned knowledge |
| **Exploration** | Random/LLM-only | Strategic (exploit + explore) |

---

## 📚 References

- [Micromouse Flood Fill Algorithm](https://en.wikipedia.org/wiki/Micromouse)
- [Reinforcement Learning: An Introduction](http://incompleteideas.net/book/the-book.html)
- [Graph-Based Web Testing](https://research.google/pubs/pub43653/)

---

**Built with ❤️ using Micromouse wisdom** 🐭✨

