from ..state import AgentState


def should_continue(state: AgentState) -> str:
    """Routing function to decide next step."""
    # Check stopping conditions
    if state.get('goal_reached'):
        return "end"
    
    if state['step_count'] >= state['max_steps']:
        print(f"\n⚠️  Max steps ({state['max_steps']}) reached")
        return "end"
    
    if state.get('stuck_count', 0) >= 2:
        print(f"\n⚠️  Agent appears stuck (failed actions: {state['stuck_count']})")
        return "end"
    
    # Do not end immediately on transient errors; keep going unless stuck/max_steps/goal.
    if state.get('error'):
        print(f"\n⚠️  Error encountered (continuing): {state['error']}")
        # Clear error so it doesn't spam subsequent iterations
        return "continue"
    
    return "continue"


