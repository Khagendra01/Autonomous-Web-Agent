from langgraph.graph import StateGraph, END
from .state import AgentState
from .planner import Planner
from .executor import Executor
from .perception import Perception
from .utils.storage import RunStorage
from .graphviz import StateGraphViz
import typer, os
from pathlib import Path
from typing import Literal


app_cli = typer.Typer()

# Global instances (to avoid reinitializing on each node call)
executor: Executor = None
perceiver: Perception = None
planner: Planner = None
storage: RunStorage = None


def observe_node(state: AgentState) -> AgentState:
    """Observe the current page state."""
    global executor
    print(f"\n[OBSERVE] Step {state.step_count}/{state.max_steps}")
    
    obs = executor.observe()
    state.observation = obs
    state.current_url = obs.get('url')
    
    # Take screenshot
    img = executor.screenshot()
    state.screenshot = img
    
    # Capture state for dataset
    _ = perceiver.detect_and_capture(state, obs, img, storage)
    
    errors = obs.get('errors', [])
    print(f"  URL: {state.current_url}")
    print(f"  Interactables: {len(obs.get('interactables', []))}")
    if errors:
        print(f"  ⚠️  ERRORS DETECTED ({len(errors)} messages):")
        for err in errors:
            print(f"     - {err}")
    
    return state


def reason_node(state: AgentState) -> AgentState:
    """Use LLM to reason and plan next action."""
    global planner
    print(f"\n[REASON] Analyzing current state...")
    
    # Show what the LLM is seeing
    errors = state.observation.get('errors', [])
    if errors:
        print(f"  ⚠️  LLM will see {len(errors)} error(s)")
    
    # Warn about repeated failures
    if state.consecutive_failures >= 2:
        print(f"  🚨 REPEATED FAILURES DETECTED: {state.consecutive_failures} consecutive '{state.failed_action_type}' failures")
        print(f"  🔄 LLM will be instructed to try alternative approaches")
    
    # Check if we have relevant knowledge
    from .knowledge import UIKB
    kb = UIKB(state.app)
    goal_lower = state.goal.lower()
    relevant_knowledge = []
    if any(word in goal_lower for word in ['create', 'add', 'new']):
        relevant_knowledge.extend(kb.query('create'))
    if relevant_knowledge:
        print(f"  💡 Using {len(relevant_knowledge)} learned UI pattern(s)")
    
    state = planner.reason_and_plan(state)
    
    print(f"  Reasoning: {state.reasoning[:150]}..." if len(state.reasoning or '') > 150 else f"  Reasoning: {state.reasoning}")
    print(f"  Current step: {state.current_step}")
    print(f"  Next action: {state.next_action}")
    
    return state


def act_node(state: AgentState) -> AgentState:
    """Execute the planned action."""
    global executor
    print(f"\n[ACT] Executing action...")
    
    action = state.next_action
    if not action:
        print("  Warning: No action planned, scrolling by default")
        action = {'type': 'scroll', 'delta': 700, 'intent': 'explore'}
    
    # Extract action info before try block so it's available in except
    action_desc = f"{action.get('type')}:{action.get('intent', 'unknown')}"
    action_type = action.get('type', 'unknown')
    
    try:
        result = executor.act(action)
        state.last_action = action_desc
        state.action_history.append(action_desc)
        state.step_count += 1
        
        # Track action result
        if result.get('ok'):
            state.last_action_result = "Success"
            state.consecutive_failures = 0  # Reset on success
            state.failed_action_type = None
            print(f"  ✓ Executed: {action_desc}")
        else:
            state.last_action_result = f"Failed: {result.get('error', 'Unknown error')}"
            # Track consecutive failures
            if state.failed_action_type == action_type:
                state.consecutive_failures += 1
            else:
                state.consecutive_failures = 1
                state.failed_action_type = action_type
            print(f"  ✗ Action failed: {result.get('error', 'Unknown error')}")
            print(f"  ⚠️  Consecutive failures: {state.consecutive_failures}")
    except Exception as e:
        print(f"  ✗ Action failed: {e}")
        state.failure_reason = str(e)
        state.last_action_result = f"Exception: {str(e)}"
        # Track consecutive failures for exceptions too
        if state.failed_action_type == action_type:
            state.consecutive_failures += 1
        else:
            state.consecutive_failures = 1
            state.failed_action_type = action_type
        print(f"  ⚠️  Consecutive failures: {state.consecutive_failures}")
    
    return state


def validate_node(state: AgentState) -> AgentState:
    """Check if the goal has been achieved."""
    global planner
    print(f"\n[VALIDATE] Checking goal completion...")
    
    state = planner.validate_completion(state)
    
    if state.done:
        print(f"  ✓ Goal completed! Success: {state.success}")
    else:
        print(f"  → Continuing (step {state.step_count}/{state.max_steps})")
    
    return state


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """Decide whether to continue or end."""
    if state.done:
        return "end"
    if state.step_count >= state.max_steps:
        print(f"\n[WARNING] Max steps ({state.max_steps}) reached!")
        state.done = True
        state.failure_reason = "Max steps reached"
        return "end"
    return "continue"


def build_graph() -> StateGraph:
    """Build the LangGraph workflow."""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("observe", observe_node)
    workflow.add_node("reason", reason_node)
    workflow.add_node("act", act_node)
    workflow.add_node("validate", validate_node)
    
    # Add edges
    workflow.set_entry_point("observe")
    workflow.add_edge("observe", "reason")
    workflow.add_edge("reason", "act")
    workflow.add_edge("act", "validate")
    
    # Conditional edge: continue or end
    workflow.add_conditional_edges(
        "validate",
        should_continue,
        {
            "continue": "observe",
            "end": END
        }
    )
    
    return workflow.compile()


@app_cli.command()
def run(
    goal: str,
    max_steps: int = typer.Option(50, help="Maximum number of steps the agent can take")
):
    """Run the autonomous agent with LangGraph orchestration."""
    global executor, perceiver, planner, storage
    
    print(f"\n{'='*60}")
    print(f"Starting Autonomous Web Agent")
    print(f"Goal: {goal}")
    print(f"{'='*60}\n")
    
    # Initialize planner first to extract app and URL from goal
    planner = Planner()
    
    print("[INIT] Extracting app and URL from goal using LLM...")
    app_info = planner.extract_app_and_url(goal)
    app = app_info['app']
    start_url = app_info['url']
    
    print(f"  ✓ App: {app}")
    print(f"  ✓ URL: {start_url}\n")
    
    # Setup
    task_slug = goal.lower().replace(' ', '_').replace('/', '-')[:60]
    storage = RunStorage('dataset', app, task_slug)
    cookies_path = os.path.join(os.getcwd(), 'auth', f'{app}-cookies.json')
    
    # Initialize components
    executor = Executor()
    perceiver = Perception()
    
    # Initialize state
    state = AgentState(
        app=app,
        goal=goal,
        cookies_path=cookies_path,
        dataset_dir=str(storage.root),
        working_dir=os.getcwd(),
        max_steps=max_steps,
    )
    
    # Init browser
    print("[INIT] Starting browser...")
    _ = executor.init(start_url, app, state.cookies_path)
    print("  ✓ Browser ready\n")
    
    # Build and run LangGraph
    graph = build_graph()
    
    try:
        # Calculate recursion limit based on workflow structure
        # Each step involves 4 nodes: observe -> reason -> act -> validate
        # So we need (max_steps * 4) + buffer for safety
        recursion_limit = (state.max_steps * 4) + 10
        print(f"[CONFIG] Max steps: {state.max_steps}, Recursion limit: {recursion_limit}\n")
        
        final_state = graph.invoke(state, {"recursion_limit": recursion_limit})
        
        # LangGraph returns dict when using Pydantic models
        if isinstance(final_state, dict):
            success = final_state.get('success', False)
            step_count = final_state.get('step_count', 0)
            dataset_dir = final_state.get('dataset_dir', '')
        else:
            success = final_state.success
            step_count = final_state.step_count
            dataset_dir = final_state.dataset_dir
        
        # Save artifacts
        storage.flush()
        print(f"\n{'='*60}")
        print(f"Task completed!")
        print(f"Success: {success}")
        print(f"Steps taken: {step_count}")
        print(f"Artifacts: {dataset_dir}")
        print(f"{'='*60}\n")
        
        # Render graphs
        try:
            viz = StateGraphViz(Path(dataset_dir))
            viz.render_linear()
            viz.render_force()
            print("Rendered: state_graph_linear.png and state_graph_force.png")
        except Exception as e:
            print(f"Graph render failed: {e}")
            
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Stopping agent...")
        storage.flush()
    except Exception as e:
        print(f"\n[ERROR] Agent failed: {e}")
        import traceback
        traceback.print_exc()
        storage.flush()


if __name__ == '__main__':
    app_cli()

