"""
Simplified Agent Graph - Minimal workflow with clean separation.

This version strips away all complexity and focuses on the core loop:
1. Observe (capture page state)
2. Plan (LLM decides action)
3. Act (execute action)
4. Check (validate completion)
"""

from langgraph.graph import StateGraph, END
from .state import AgentState
from .planner_simple import SimplePlanner
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
    
    # ⚡ Show priority buttons found
    interactables = obs.get('interactables', [])
    priority_count = sum(1 for item in interactables 
                        if any(word in (item.get('label') or '').lower() 
                               for word in ['create', 'new', 'add', '+']))
    if priority_count > 0:
        print(f"  🎯 Found {priority_count} create/new/add button(s)")
    
    return state


def plan_node(state: AgentState) -> AgentState:
    """Plan next action using LLM."""
    print(f"\n[PLAN] Planning next action...")
    state = planner.plan_next_action(state)
    return state


def act_node(state: AgentState) -> AgentState:
    """Execute the planned action."""
    print(f"\n[ACT] Executing...")
    
    action = state.next_action or {'type': 'scroll', 'delta': 700}
    
    try:
        result = executor.act(action)
        state.last_action = f"{action.get('type')}:{action.get('intent', 'action')}"
        state.action_history.append(state.last_action)
        state.step_count += 1
        
        # ⚡ Track action results for LLM feedback
        if result.get('ok'):
            state.last_action_result = "✓ Success"
            print(f"  ✓ Success")
        else:
            error_msg = result.get('error', 'Unknown error')
            state.last_action_result = f"✗ Failed: {error_msg}"
            print(f"  ✗ Failed: {error_msg}")
            
    except Exception as e:
        state.last_action_result = f"✗ Exception: {str(e)}"
        print(f"  ✗ Error: {e}")
    
    return state


def check_node(state: AgentState) -> AgentState:
    """Check if goal is complete."""
    print(f"\n[CHECK] Validating completion...")
    state = planner.check_completion(state)
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
    """Build the simple workflow graph."""
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
    max_steps: int = typer.Option(30, help="Maximum steps")
):
    """Run the simplified agent."""
    global executor, perceiver, planner, storage
    
    print(f"\n{'='*60}")
    print(f"🤖 Simplified Autonomous Agent")
    print(f"Goal: {goal}")
    print(f"{'='*60}\n")
    
    # Initialize
    planner = SimplePlanner()
    
    print("[INIT] Extracting app and URL...")
    app_info = planner.extract_app_and_url(goal)
    app = app_info['app']
    start_url = app_info['url']
    
    print(f"  App: {app}")
    print(f"  URL: {start_url}\n")
    
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
        
        # Save
        storage.flush()
        
        print(f"\n{'='*60}")
        print(f"✅ Task Complete!")
        print(f"Success: {success}")
        print(f"Steps: {step_count}")
        print(f"{'='*60}\n")
        
    except KeyboardInterrupt:
        print("\n[STOPPED] Interrupted by user")
        storage.flush()
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        storage.flush()


if __name__ == '__main__':
    app_cli()

