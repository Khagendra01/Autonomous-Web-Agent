"""Main runner for the autonomous web agent."""
import sys
import argparse
import requests
from pathlib import Path
from urllib.parse import urlparse
from .workflow import create_agent_workflow
from ..drivers.grpc_client import DriverClient
from .state import AgentState
from .utils.storage import RunStorage
from .utils.logger import setup_logging, get_logger, AgentLogger
from dotenv import load_dotenv


def initialize_driver(app_name: str, start_url: str):
    """Initialize the Playwright driver."""
    logger = get_logger()
    
    logger.info("=" * 60)
    logger.info(f"🚀 Initializing driver for {app_name}")
    logger.info("=" * 60)
    
    payload = {
        'app': app_name,
        'url': start_url,
    }
    
    try:
        client = DriverClient()
        resp = client.init(app_name, start_url)
        if not resp.ok:
            raise RuntimeError(f"Driver initialization failed: {resp.error}")
        logger.info(f"✓ Driver initialized successfully")
        logger.info(f"✓ Navigated to: {start_url}")
        return True
    except Exception as e:
        logger.error("\n❌ Cannot connect to driver!")
        logger.error("Please start the gRPC driver server first:")
        logger.error("  python -m src.drivers.grpc_playwright_server")
        logger.error(f"Details: {e}")
        return False


def extract_app_name(url: str) -> str:
    """Extract app name from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace('www.', '')
    # Get first part of domain (e.g., 'linear' from 'linear.app')
    app_name = domain.split('.')[0]
    return app_name.capitalize()


def run_task(
    goal: str | None = None,
    start_url: str | None = None,
    app_name: str | None = None,
    instruction: str | None = None,
    max_steps: int = 15,
    output_dir: str = "captures",
    recursion_limit: int = 60,
):
    """Run an autonomous task with a given goal.
    
    Args:
        goal: Natural language description of what to accomplish
        start_url: URL to start from
        app_name: Optional app name (auto-detected from URL if not provided)
        max_steps: Maximum number of steps to take
        output_dir: Directory to save captures
    """
    # Ensure environment variables from .env are loaded (OPENAI_API_KEY, etc.)
    load_dotenv()

    # Determine mode: instruction-only vs explicit goal/url
    instruction_only = instruction is not None and (goal is None and start_url is None)

    # Auto-detect app name if not provided (explicit mode)
    if not instruction_only and not app_name and start_url:
        app_name = extract_app_name(start_url)
    
    # Create storage with sanitized task name (need this first to get log file path)
    import re
    task_slug_source = (goal or instruction or 'task').lower()
    task_slug = re.sub(r'[^a-z0-9_-]', '_', task_slug_source[:50])
    
    storage = RunStorage(
        base_dir=output_dir,
        app=(app_name or 'webapp').lower(),
        task_slug=task_slug
    )
    
    # Set up logging to both console and file (do this early)
    log_file_path = storage.get_log_file_path()
    logger = setup_logging(
        log_file_path=log_file_path,
        level=20,  # INFO level
        console_level=20  # INFO level
    )
    
    logger.info("=" * 60)
    if instruction_only:
        logger.info(f"📝 Instruction: {instruction}")
    else:
        logger.info(f"🎯 Goal: {goal}")
        logger.info(f"🌐 Start URL: {start_url}")
        logger.info(f"📱 App: {app_name}")
    logger.info("=" * 60)
    
    # Initialize driver only in explicit mode; in instruction-only mode, bootstrap node handles init
    if not instruction_only:
        if not initialize_driver(app_name, start_url):
            return False
    
    logger.info("=" * 60)
    logger.info("🤖 Starting autonomous agent workflow")
    logger.info("=" * 60)
    
    # Create initial state
    initial_state: AgentState = {
        'instruction': instruction or (goal or ''),
        'goal': goal or (instruction or ''),
        'multiple_goal': None,
        'current_goal': None,
        'app_name': app_name or '',
        'base_url': start_url or '',
        'max_steps': max_steps,
        'step_count': 0,
        'current_url': start_url or '',
        'screenshot_bytes': None,
        'dom_snapshot': None,
        'interactable_elements': [],
        'errors': [],
        'action_history': [],
        'screenshots': [],
        'scored_actions': [],
        'next_action': None,
        'goal_reached': False,
        'error': None,
        'stuck_count': 0,
        'tried_actions_by_url': {},
        'prioritized_roles': [],
    }
    
    workflow = create_agent_workflow()
    
    try:
        # Run the workflow
        final_state = workflow.invoke(initial_state, config={
            "recursion_limit": recursion_limit
        })
        
        # Save results
        logger.info("=" * 60)
        logger.info("💾 Saving results")
        logger.info("=" * 60)
        
        # Save screenshots per step, pairing full and focused where available
        screenshots = final_state.get('screenshots') or []
        focused_after_steps = set(final_state.get('focused_after_steps') or [])

        j = 0  # index into screenshots list
        step = 0
        while j < len(screenshots):
            # Full screenshot for this step
            full_name = f"step_{step:03d}.png"
            storage.save_screenshot(screenshots[j], full_name)
            logger.info(f"  Saved: {full_name}")

            # Optional focused screenshot for this step
            screenshot_list = [full_name]
            if step in focused_after_steps and (j + 1) < len(screenshots):
                crop_name = f"step_{step:03d}_focus.png"
                storage.save_screenshot(screenshots[j + 1], crop_name)
                logger.info(f"  Saved: {crop_name}")
                # Bundle cropped image with its parent as a list
                screenshot_list.append(crop_name)
                j += 2
            else:
                j += 1

            # Add to manifest with bundled list [full, focused] when crop exists, [full] otherwise
            action = final_state['action_history'][step] if step < len(final_state['action_history']) else None
            storage.append_state({
                'step': step,
                'screenshot': screenshot_list,
                'url': final_state['current_url'] if step == (final_state['step_count'] - 1) else None,
                'action': action,
            })

            step += 1
        
        # Save manifest
        storage.flush()
        
        # Print summary
        logger.info("=" * 60)
        logger.info("✅ Task completed!")
        logger.info("=" * 60)
        logger.info("📊 Summary:")
        logger.info(f"  Steps taken: {final_state['step_count']}")
        logger.info(f"  Screenshots captured: {len(final_state['screenshots'])}")
        logger.info(f"  Goal reached: {'Yes ✓' if final_state['goal_reached'] else 'No ✗'}")
        logger.info(f"  Output directory: {storage.root}")
        logger.info(f"  Log file: {storage.get_log_file_path()}")
        
        if final_state.get('error'):
            logger.error(f"  Error: {final_state['error']}")
        
        logger.info("=" * 60)
        
        return True
        
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Interrupted by user")
        return False
    except Exception as e:
        logger.error(f"\n\n❌ Error during workflow execution: {e}")
        import traceback
        logger.exception("Full traceback:")
        return False
    finally:
        # Always shutdown logger to ensure file is saved
        AgentLogger.shutdown()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous Web Agent - Task-Agnostic UI Capture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a project in Linear
  python -m src.agents.runner "Create a new project in Linear"
  
  # Create a GitHub issue
  python -m src.agents.runner "Create a new issue in this GitHub repo"

Make sure the driver is running first:
  python -m src.drivers.playwright_driver
        """
    )
    
    # Positional instruction enables instruction-only mode
    parser.add_argument('instruction', nargs='?', help='Natural language instruction (app + goal)')
    
    # Optional explicit flags (backward compatible)
    parser.add_argument('--goal', '-g', help='Goal to accomplish (explicit mode)')
    parser.add_argument('--url', '-u', help='Starting URL (explicit mode)')
    parser.add_argument('--app', '-a', help='Application name (explicit mode)')
    
    parser.add_argument(
        '--max-steps', '-m',
        type=int,
        default=15,
        help='Maximum number of steps to take (default: 15)'
    )
    parser.add_argument(
        '--recursion-limit', '-r',
        type=int,
        default=60,
        help='Max graph recursion limit before stopping (default: 60)'
    )
    
    parser.add_argument(
        '--output', '-o',
        default='captures',
        help='Output directory for captures (default: captures)'
    )
    
    args = parser.parse_args()
    
    # Decide mode
    instruction_only = args.instruction and (not args.goal and not args.url)
    
    success = run_task(
        goal=None if instruction_only else args.goal,
        start_url=None if instruction_only else args.url,
        app_name=None if instruction_only else args.app,
        instruction=args.instruction if instruction_only else None,
        max_steps=args.max_steps,
        output_dir=args.output,
        recursion_limit=args.recursion_limit
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

