from langgraph.graph import StateGraph
from .state import AgentState
from .planner import Planner
from .executor import Executor
from .perception import Perception
from .utils.storage import RunStorage
from .graphviz import StateGraphViz
import typer, os
from pathlib import Path


app_cli = typer.Typer()


@app_cli.command()
def run(app: str, goal: str):
    # Basic task slug
    task_slug = goal.lower().replace(' ', '_').replace('/', '-')[:60]
    storage = RunStorage('dataset', app, task_slug)

    state = AgentState(
        app=app,
        goal=goal,
        cookies_path=f'auth/{app}-cookies.json',
        dataset_dir=str(storage.root),
        working_dir=os.getcwd(),
    )

    executor = Executor()
    perceiver = Perception()
    planner = Planner()

    # init browser
    _ = executor.init(app, state.cookies_path)

    while not state.done:
        obs = executor.observe()  # includes URL, a11y snapshot, interactables
        state.observation = obs
        state.current_url = obs.get('url')

        # screenshot + perception
        img = executor.screenshot()
        _ = perceiver.detect_and_capture(state, obs, img, storage)

        # quick success heuristic example: look for toast/hint
        if 'create' in goal.lower() and 'project' in goal.lower():
            hint = (obs.get('hint') or '').lower()
            if 'created' in hint:
                state.done = True
                state.success = True
                break

        # plan next action
        action = planner.plan_next(state, img)
        state.last_action = action.get('intent') or action.get('type')
        executor.act(action)

    storage.flush()
    print(f"Artifacts written to: {state.dataset_dir}")

    # Render both graphs
    try:
        viz = StateGraphViz(Path(state.dataset_dir))
        viz.render_linear()
        viz.render_force()
        print("Rendered: state_graph_linear.png and state_graph_force.png")
    except Exception as e:
        print("Graph render failed:", e)


if __name__ == '__main__':
    app_cli()

