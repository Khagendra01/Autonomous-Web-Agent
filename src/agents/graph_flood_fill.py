"""
Flood Fill Agent Graph - Autonomous exploration using State Space Graph.

Inspired by Micromouse maze solving:
- Explores UI state space autonomously
- Learns optimal paths via flood fill
- Reuses knowledge across runs
"""

from langgraph.graph import StateGraph, END
from .state import AgentState
from .planner_flood_fill import FloodFillPlanner
from .executor import Executor
from .perception import Perception
from .utils.storage import RunStorage
import typer
import os
from typing import Literal


app_cli = typer.Typer()

# Global instances
executor = None
perceiver = None
planner = None
storage = None


def observe_node(state: AgentState) -> AgentState:
    """Capture current page state."""
    print(f"\n[OBSERVE] Step {state.step_count}/{state.max_steps}")
    
    # Get page state
    obs = executor.observe()
    state.observation = obs
    state.current_url = obs.get('url')
    
    # Take screenshot
    img = executor.screenshot()
    state.screenshot = img
    
    # Save to dataset
    perceiver.detect_and_capture(state, obs, img, storage)
    
    print(f"  URL: {state.current_url}")
    print(f"  Elements: {len(obs.get('interactables', []))}")
    
    return state


def plan_node(state: AgentState) -> AgentState:
    """Plan next action using Flood Fill strategy."""
    print(f"\n[PLAN] Planning with flood fill...")
    state = planner.plan_next_action(state)
    return state


def act_node(state: AgentState) -> AgentState:
    """Execute the planned action and log what happened."""
    print(f"\n[ACT] Executing...")
    
    action = state.next_action or {'type': 'scroll', 'delta': 700}
    
    # Build human-readable action description
    action_type = action.get('type', 'unknown')
    if action_type == 'type':
        action_desc = f"type '{action.get('text', '')}' in {action.get('selector', 'field')}"
    elif action_type == 'click':
        selector = action.get('selector', '')
        if 'name="' in selector:
            label = selector.split('name="')[1].split('"')[0]
            action_desc = f"click '{label}'"
        else:
            action_desc = f"click {selector}"
    else:
        action_desc = f"scroll {action.get('delta', 0)}px"
    
    try:
        result = executor.act(action)
        state.last_action = f"{action.get('type')}:{action.get('intent', 'action')}"
        state.action_history.append(state.last_action)
        state.step_count += 1
        
        if result.get('ok'):
            state.last_action_result = "✓ Success"
            result_str = "✓ Success"
            print(f"  ✓ Success")
        else:
            error_msg = result.get('error', 'Unknown error')
            state.last_action_result = f"✗ Failed: {error_msg}"
            result_str = f"✗ Failed: {error_msg}"
            print(f"  ✗ Failed: {error_msg}")
        
        # Log to rich action history
        from .state import ActionLog
        log = ActionLog(
            step=state.step_count,
            intent=state.reasoning or "No reasoning provided",
            action=action_desc,
            result=result_str
        )
        state.memory.action_logs.append(log)
            
    except Exception as e:
        state.last_action_result = f"✗ Exception: {str(e)}"
        result_str = f"✗ Exception: {str(e)}"
        print(f"  ✗ Error: {e}")
        
        from .state import ActionLog
        log = ActionLog(
            step=state.step_count,
            intent=state.reasoning or "No reasoning provided",
            action=action_desc,
            result=result_str
        )
        state.memory.action_logs.append(log)
    
    return state


def check_node(state: AgentState) -> AgentState:
    """Check if goal is complete using flood fill planner."""
    print(f"\n[CHECK] Validating completion...")
    
    # Use planner's LLM-based goal checking
    goal_reached = planner.check_if_goal(state)
    
    if goal_reached:
        state.done = True
        state.success = True
    elif state.current_fingerprint:
        # Estimate distance for current state
        distance = planner.estimate_goal_distance(state)
        print(f"[DISTANCE] {distance:.2f} (0=goal, 1=far)")
    
    return state


def should_continue(state: AgentState) -> Literal["continue", "end"]:
    """Decide to continue or end."""
    if state.done:
        return "end"
    if state.step_count >= state.max_steps:
        print(f"\n[WARNING] Max steps reached")
        state.done = True
        return "end"
    return "continue"


def build_graph():
    """Build the flood fill workflow graph."""
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("observe", observe_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("act", act_node)
    workflow.add_node("check", check_node)
    
    # Connect nodes
    workflow.set_entry_point("observe")
    workflow.add_edge("observe", "plan")
    workflow.add_edge("plan", "act")
    workflow.add_edge("act", "check")
    
    # Loop or end
    workflow.add_conditional_edges(
        "check",
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
    max_steps: int = typer.Option(50, help="Maximum steps")
):
    """Run the flood fill agent."""
    global executor, perceiver, planner, storage
    
    print(f"\n{'='*60}")
    print(f"🐭 FLOOD FILL Autonomous Agent")
    print(f"Goal: {goal}")
    print(f"{'='*60}\n")
    
    # Initialize temporary planner to extract app info
    temp_planner = FloodFillPlanner(app_name="temp")
    
    print("[INIT] Extracting app and URL...")
    app_info = temp_planner.extract_app_and_url(goal)
    app = app_info['app']
    start_url = app_info['url']
    
    print(f"  App: {app}")
    print(f"  URL: {start_url}\n")
    
    # Initialize flood fill planner for this app
    planner = FloodFillPlanner(app_name=app)
    
    # Setup storage
    task_slug = goal.lower().replace(' ', '_')[:60]
    storage = RunStorage('dataset', app, task_slug)
    cookies_path = os.path.join(os.getcwd(), 'auth', f'{app}-cookies.json')
    
    # Initialize components
    executor = Executor()
    perceiver = Perception()
    
    # Create initial state
    state = AgentState(
        app=app,
        goal=goal,
        cookies_path=cookies_path,
        dataset_dir=str(storage.root),
        working_dir=os.getcwd(),
        max_steps=max_steps,
    )
    
    # Start browser
    print("[INIT] Starting browser...")
    executor.init(start_url, app, cookies_path)
    print("  ✓ Browser ready\n")
    
    # Build and run graph
    graph = build_graph()
    
    try:
        recursion_limit = (max_steps * 4) + 10
        final_state = graph.invoke(state, {"recursion_limit": recursion_limit})
        
        # Extract results
        if isinstance(final_state, dict):
            success = final_state.get('success', False)
            step_count = final_state.get('step_count', 0)
        else:
            success = final_state.success
            step_count = final_state.step_count
        
        # Save graph knowledge
        planner.save_graph()
        
        # Save run data
        storage.flush()
        
        print(f"\n{'='*60}")
        print(f"✅ Task Complete!")
        print(f"Success: {success}")
        print(f"Steps: {step_count}")
        
        # Show graph stats
        stats = planner.graph.get_statistics()
        print(f"\n📊 State Graph:")
        print(f"  States explored: {stats['total_states']}")
        print(f"  Transitions learned: {stats['total_transitions']}")
        print(f"  Goal states: {stats['goal_states']}")
        print(f"{'='*60}\n")
        
    except KeyboardInterrupt:
        print("\n[STOPPED] Interrupted by user")
        planner.save_graph()
        storage.flush()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        planner.save_graph()
        storage.flush()


if __name__ == '__main__':
    app_cli()

