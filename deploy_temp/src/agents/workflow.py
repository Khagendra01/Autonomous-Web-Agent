"""LangGraph workflow for the autonomous web agent."""
from langgraph.graph import StateGraph, END
from .state import AgentState
from .nodes import (
    bootstrap_node,
    observe_node,
    score_actions_node,
    decide_action_node,
    execute_action_node,
    check_goal_node,
    should_continue,
)


def create_agent_workflow():
    """Create the LangGraph workflow for autonomous web navigation."""
    
    # Create the graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("bootstrap", bootstrap_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("score_actions", score_actions_node)
    workflow.add_node("decide_action", decide_action_node)
    workflow.add_node("execute_action", execute_action_node)
    workflow.add_node("check_goal", check_goal_node)
    
    # Define the flow
    workflow.set_entry_point("bootstrap")
    
    # bootstrap -> observe
    workflow.add_edge("bootstrap", "observe")

    # observe -> score_actions
    workflow.add_edge("observe", "score_actions")
    
    # score_actions -> decide_action -> execute_action
    workflow.add_edge("score_actions", "decide_action")
    workflow.add_edge("decide_action", "execute_action")
    
    # execute_action -> check_goal
    workflow.add_edge("execute_action", "check_goal")
    
    # check_goal -> continue/end
    workflow.add_conditional_edges(
        "check_goal",
        should_continue,
        {
            "continue": "observe",  # Loop back to observe
            "end": END
        }
    )
    
    return workflow.compile()

