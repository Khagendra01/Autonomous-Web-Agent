"""Example showing how to use the enhanced components together."""
from typing import Dict, Any

# This is a conceptual example - integrate into your actual workflow

def example_enhanced_observe(state: Dict[str, Any]) -> Dict[str, Any]:
    """Example of using enhanced observe node."""
    from ..nodes.observe_enhanced import observe_node
    
    # Call enhanced observe - it automatically:
    # 1. Processes elements into selector_map
    # 2. Adds structured metadata
    # 3. Creates LLM-friendly format
    updated_state = observe_node(state)
    
    # Now state has 'selector_map' available
    selector_map = updated_state.get('selector_map')
    
    if selector_map:
        # Access elements by index
        element_0 = selector_map.get_element(0)
        print(f"Element 0: {element_0}")
        
        # Get LLM-friendly serialization
        llm_format = selector_map.serialize_for_llm()
        print(f"LLM format preview:\n{llm_format[:200]}...")
    
    return updated_state


def example_enhanced_scoring(state: Dict[str, Any]) -> Dict[str, Any]:
    """Example of using enhanced scoring node."""
    from ..nodes.scoring_enhanced import score_actions_node
    
    # Enhanced scoring automatically:
    # 1. Uses formatted prompts
    # 2. Better context organization
    # 3. Improved error handling
    result = score_actions_node(state)
    
    # Get scored actions
    scored_actions = result.get('scored_actions', [])
    
    print(f"Found {len(scored_actions)} scored actions:")
    for action in scored_actions[:5]:
        print(f"  [{action.score:.1f}] {action.action_type} '{action.label}'")
        print(f"      Reasoning: {action.reasoning[:60]}...")
    
    return result


def example_message_formatting(state: Dict[str, Any]):
    """Example of using message formatter directly."""
    from ..utils.message_formatter import AgentMessageFormatter
    
    formatter = AgentMessageFormatter(
        goal=state.get('goal', ''),
        instruction=state.get('instruction', ''),
        current_url=state.get('current_url', ''),
        step_count=state.get('step_count', 0),
        max_steps=state.get('max_steps', 15),
    )
    
    # Get selector map (from enhanced observe)
    selector_map = state.get('selector_map')
    if not selector_map:
        return
    
    # Format complete message
    message = formatter.format_state_message(
        selector_map=selector_map,
        action_history=state.get('action_history', []),
        errors=state.get('errors', []),
        screenshot_available=bool(state.get('screenshot_bytes')),
        goal_evaluation=state.get('goal_evaluation', {}),
    )
    
    print("Formatted message:")
    print("=" * 60)
    print(message)
    print("=" * 60)


def example_structured_actions():
    """Example of using structured action models."""
    from ..action_models import ClickAction, TypeAction, ActionResult
    
    # Create type-safe actions
    click_action = ClickAction(
        selector="button.submit",
        label="Submit Button",
        index=5,
    )
    
    type_action = TypeAction(
        selector="input.email",
        label="Email Input",
        text="user@example.com",
        index=3,
    )
    
    # Create structured result
    result = ActionResult(
        success=True,
        extracted_content="Form submitted successfully",
        long_term_memory="User is now on confirmation page",
        metadata={
            'clicked_element': 'button.submit',
            'timestamp': '2024-01-01T12:00:00Z',
        },
    )
    
    print(f"Click action: {click_action.action_type} on {click_action.selector}")
    print(f"Type action: '{type_action.text}' into {type_action.selector}")
    print(f"Result: {'✅ Success' if result.success else '❌ Failed'}")
    if result.extracted_content:
        print(f"Extracted: {result.extracted_content}")


def example_integrated_workflow_step(state: Dict[str, Any]) -> Dict[str, Any]:
    """Example of a complete workflow step using enhanced components."""
    
    # Step 1: Enhanced observe
    print("\n=== OBSERVE STEP ===")
    state = example_enhanced_observe(state)
    
    # Step 2: Enhanced scoring
    print("\n=== SCORE STEP ===")
    scoring_result = example_enhanced_scoring(state)
    state.update(scoring_result)
    
    # Step 3: (Optional) View formatted message
    print("\n=== FORMATTED MESSAGE ===")
    example_message_formatting(state)
    
    # Step 4: Decision and execution would happen here
    # ... (using your existing decision_node and execute_action_node)
    
    return state


if __name__ == "__main__":
    # Example state
    example_state = {
        'goal': 'Create a new issue in GitHub',
        'instruction': 'Create a new issue',
        'current_url': 'https://github.com/owner/repo',
        'step_count': 0,
        'max_steps': 15,
        'action_history': [],
        'errors': [],
        'screenshots': [],
    }
    
    # Run integrated example
    print("=" * 60)
    print("ENHANCED COMPONENTS USAGE EXAMPLE")
    print("=" * 60)
    
    # Show structured actions
    print("\n--- Structured Actions Example ---")
    example_structured_actions()
    
    # Note: Full workflow example would require actual driver connection
    # print("\n--- Integrated Workflow Step ---")
    # example_integrated_workflow_step(example_state)

