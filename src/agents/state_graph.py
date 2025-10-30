"""
State Space Flood Fill Agent - Core Graph Implementation

Inspired by Micromouse flood fill algorithm:
- Each UI state is a "cell" in the maze
- Distance values propagate from goal state (flood fill)
- Agent chooses actions that lead to lowest distance neighbors
- Learns optimal paths through exploration
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Tuple
import json
import os
from pathlib import Path


class Transition(BaseModel):
    """Represents an action that moves from one state to another."""
    action_type: str  # click, type, scroll
    action_selector: Optional[str] = None
    action_text: Optional[str] = None
    from_state: str  # Source state fingerprint
    to_state: str  # Destination state fingerprint
    success_count: int = 0
    failure_count: int = 0
    cost: float = 1.0  # Default cost
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate of this transition."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5  # Unknown, assume 50%
        return self.success_count / total
    
    def record_result(self, success: bool):
        """Update transition statistics."""
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1


class UIState(BaseModel):
    """Represents a unique UI state in the web application."""
    fingerprint: str  # DOM fingerprint (unique ID)
    url: str
    elements_count: int
    visited_count: int = 0
    distance_to_goal: float = float('inf')
    is_goal: bool = False
    goal_score: Optional[float] = None  # LLM-estimated closeness to goal (0-1)
    
    # Available actions from this state
    transitions: Dict[str, Transition] = Field(default_factory=dict)
    
    def add_transition(self, action_key: str, transition: Transition):
        """Add or update a transition from this state."""
        self.transitions[action_key] = transition
    
    def get_best_action(self, state_graph: StateGraph) -> Optional[Tuple[str, Transition]]:
        """Get action leading to lowest distance neighbor (like micromouse)."""
        if not self.transitions:
            return None
        
        best_score = float('inf')
        best_action = None
        
        for action_key, transition in self.transitions.items():
            # Get neighbor state
            neighbor = state_graph.states.get(transition.to_state)
            if not neighbor:
                continue
            
            # Score = neighbor distance + penalties
            score = (
                neighbor.distance_to_goal * 1.0 +  # Main factor: distance
                (1 - transition.success_rate) * 0.5 +  # Penalty for unreliable transitions
                transition.cost * 0.1  # Small cost factor
            )
            
            if score < best_score:
                best_score = score
                best_action = (action_key, transition)
        
        return best_action


class StateGraph(BaseModel):
    """The state space graph for a web application."""
    app_name: str
    states: Dict[str, UIState] = Field(default_factory=dict)
    goal_state_fingerprint: Optional[str] = None
    
    def add_state(self, fingerprint: str, url: str, elements_count: int) -> UIState:
        """Add or get existing state."""
        if fingerprint in self.states:
            state = self.states[fingerprint]
            state.visited_count += 1
            return state
        
        state = UIState(
            fingerprint=fingerprint,
            url=url,
            elements_count=elements_count,
            visited_count=1
        )
        self.states[fingerprint] = state
        return state
    
    def add_transition(
        self,
        from_fingerprint: str,
        to_fingerprint: str,
        action_type: str,
        selector: Optional[str] = None,
        text: Optional[str] = None,
        success: bool = True
    ):
        """Add or update a transition between states."""
        from_state = self.states.get(from_fingerprint)
        if not from_state:
            return
        
        # Create action key
        action_key = f"{action_type}:{selector or 'none'}:{text or ''}"
        
        # Get or create transition
        if action_key in from_state.transitions:
            transition = from_state.transitions[action_key]
            transition.record_result(success)
        else:
            transition = Transition(
                action_type=action_type,
                action_selector=selector,
                action_text=text,
                from_state=from_fingerprint,
                to_state=to_fingerprint,
                success_count=1 if success else 0,
                failure_count=0 if success else 1
            )
            from_state.add_transition(action_key, transition)
    
    def set_goal_state(self, fingerprint: str):
        """Mark a state as the goal and trigger flood fill."""
        if fingerprint in self.states:
            self.states[fingerprint].is_goal = True
            self.states[fingerprint].distance_to_goal = 0
            self.goal_state_fingerprint = fingerprint
            self.flood_fill()
    
    def flood_fill(self):
        """Calculate distances using flood fill algorithm (like micromouse)."""
        if not self.goal_state_fingerprint:
            return
        
        # Initialize: goal = 0, all others = inf
        for state in self.states.values():
            if not state.is_goal:
                state.distance_to_goal = float('inf')
        
        # Propagate distances (like water flooding from goal)
        changed = True
        iterations = 0
        max_iterations = 100
        
        while changed and iterations < max_iterations:
            changed = False
            iterations += 1
            
            for state in self.states.values():
                # For each state, check if any neighbor offers shorter path
                for transition in state.transitions.values():
                    neighbor = self.states.get(transition.to_state)
                    if not neighbor:
                        continue
                    
                    # Calculate potential new distance
                    new_distance = neighbor.distance_to_goal + transition.cost
                    
                    # Update if better path found
                    if new_distance < state.distance_to_goal:
                        state.distance_to_goal = new_distance
                        changed = True
        
        print(f"[FLOOD FILL] Converged in {iterations} iterations")
    
    def get_unexplored_actions(self, current_state: UIState, available_actions: List[Dict]) -> List[Dict]:
        """Get actions that haven't been tried yet (exploration)."""
        tried_selectors = set()
        for transition in current_state.transitions.values():
            if transition.action_selector:
                tried_selectors.add(transition.action_selector)
        
        # If state has been visited many times, also consider failed transitions
        # to avoid retrying actions that consistently don't help
        if current_state.visited_count > 3:
            for transition in current_state.transitions.values():
                # Mark transitions with low success rate as "tried" to deprioritize them
                if transition.success_rate < 0.3 and transition.action_selector:
                    tried_selectors.add(transition.action_selector)
        
        unexplored = []
        for action in available_actions:
            selector = action.get('selector', '')
            if selector not in tried_selectors:
                unexplored.append(action)
        
        return unexplored
    
    def save(self, directory: str):
        """Save state graph to disk."""
        Path(directory).mkdir(parents=True, exist_ok=True)
        filepath = os.path.join(directory, f"{self.app_name}_graph.json")
        
        with open(filepath, 'w') as f:
            json.dump(self.model_dump(mode='json'), f, indent=2)
        
        print(f"[GRAPH] Saved to {filepath}")
    
    @classmethod
    def load(cls, app_name: str, directory: str) -> Optional[StateGraph]:
        """Load state graph from disk."""
        filepath = os.path.join(directory, f"{app_name}_graph.json")
        
        if not os.path.exists(filepath):
            return None
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        graph = cls(**data)
        print(f"[GRAPH] Loaded {len(graph.states)} states from {filepath}")
        return graph
    
    def get_statistics(self) -> Dict:
        """Get graph statistics."""
        total_transitions = sum(len(s.transitions) for s in self.states.values())
        goal_states = sum(1 for s in self.states.values() if s.is_goal)
        
        return {
            'total_states': len(self.states),
            'total_transitions': total_transitions,
            'goal_states': goal_states,
            'most_visited': max((s.visited_count for s in self.states.values()), default=0)
        }

