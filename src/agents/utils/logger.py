"""Logging utility for the autonomous web agent."""
import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


class FlushingFileHandler(logging.FileHandler):
    """File handler that flushes immediately after each log message."""
    
    def emit(self, record):
        """Emit a record and flush immediately."""
        super().emit(record)
        self.flush()


class AgentLogger:
    """Centralized logger that writes to both console and file."""
    
    _logger: Optional[logging.Logger] = None
    _file_handler: Optional[logging.FileHandler] = None
    _log_file_path: Optional[Path] = None
    
    @classmethod
    def setup(
        cls,
        log_file_path: Optional[Path] = None,
        level: int = logging.INFO,
        console_level: int = logging.INFO,
        format_string: Optional[str] = None
    ) -> logging.Logger:
        """
        Set up the logger with both console and file handlers.
        
        Args:
            log_file_path: Path to log file. If None, logs only to console.
            level: Overall logging level (both console and file)
            console_level: Console-specific logging level
            format_string: Custom format string for log messages
        
        Returns:
            The configured logger instance
        """
        if cls._logger is not None:
            # Already setup, just return it
            return cls._logger
        
        # Create logger
        logger = logging.getLogger('autonomous_agent')
        logger.setLevel(level)
        
        # Prevent duplicate logs from propagation
        logger.propagate = False
        
        # Default format
        if format_string is None:
            format_string = '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
        formatter = logging.Formatter(format_string, datefmt='%Y-%m-%d %H:%M:%S')
        
        # Console handler (stdout)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File handler (if path provided)
        if log_file_path:
            # Ensure parent directory exists
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Use FlushingFileHandler to write logs immediately
            file_handler = FlushingFileHandler(log_file_path, mode='w', encoding='utf-8')
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            
            cls._file_handler = file_handler
            cls._log_file_path = log_file_path
            
            # Log file location
            logger.info(f"Logging to file: {log_file_path}")
        
        cls._logger = logger
        return logger
    
    @classmethod
    def get_logger(cls) -> logging.Logger:
        """
        Get the logger instance. Sets up a default logger if not already configured.
        
        Returns:
            The logger instance
        """
        if cls._logger is None:
            # Set up a default console-only logger
            return cls.setup()
        return cls._logger
    
    @classmethod
    def get_log_file_path(cls) -> Optional[Path]:
        """Get the path to the current log file, if any."""
        return cls._log_file_path
    
    @classmethod
    def shutdown(cls):
        """Close file handlers and cleanup."""
        if cls._file_handler:
            cls._file_handler.flush()
            cls._file_handler.close()
            if cls._logger:
                cls._logger.removeHandler(cls._file_handler)
            cls._file_handler = None
        
        if cls._logger:
            # Flush all handlers before shutdown
            for handler in cls._logger.handlers[:]:
                handler.flush()
                if hasattr(handler, 'close'):
                    handler.close()
                cls._logger.removeHandler(handler)
        
        cls._logger = None
        cls._log_file_path = None


def get_logger() -> logging.Logger:
    """
    Convenience function to get the agent logger.
    
    Returns:
        The logger instance
    """
    return AgentLogger.get_logger()


def setup_logging(
    log_file_path: Optional[Path] = None,
    level: int = logging.INFO,
    console_level: int = logging.INFO
) -> logging.Logger:
    """
    Convenience function to set up logging.
    
    Args:
        log_file_path: Path to log file. If None, logs only to console.
        level: Overall logging level (both console and file)
        console_level: Console-specific logging level
    
    Returns:
        The configured logger instance
    """
    return AgentLogger.setup(log_file_path, level, console_level)


def log_agent_state(state: dict, step_label: str = ""):
    """
    Log detailed agent state information to the log file.
    
    Args:
        state: The AgentState dictionary
        step_label: Optional label for this state snapshot (e.g., "After Step 3")
    """
    logger = get_logger()
    import json
    
    logger.info("")
    logger.info("=" * 60)
    if step_label:
        logger.info(f"[STATE] {step_label}")
    else:
        logger.info("[STATE] Current Agent State")
    logger.info("=" * 60)
    
    # Basic info
    logger.info(f"Step Count: {state.get('step_count', 0)}")
    logger.info(f"Goal: {state.get('goal', 'N/A')}")
    logger.info(f"Current URL: {state.get('current_url', 'N/A')}")
    logger.info(f"Goal Reached: {state.get('goal_reached', False)}")
    logger.info(f"App Name: {state.get('app_name', 'N/A')}")
    logger.info(f"Base URL: {state.get('base_url', 'N/A')}")
    
    # Status
    if state.get('error'):
        logger.info(f"Error: {state.get('error')}")
    if state.get('stuck_count', 0) > 0:
        logger.info(f"Stuck Count: {state.get('stuck_count', 0)}")
    
    # Prioritized roles
    prioritized = state.get('prioritized_roles')
    if prioritized:
        logger.info(f"Prioritized Roles: {prioritized}")
    
    # Action history
    action_history = state.get('action_history', [])
    logger.info(f"\nAction History ({len(action_history)} actions):")
    for i, action in enumerate(action_history):
        action_str = json.dumps(action, indent=2, default=str) if isinstance(action, dict) else str(action)
        logger.info(f"  [{i}] {action_str}")
    
    # Scored actions (summary)
    scored_actions = state.get('scored_actions', [])
    if scored_actions:
        logger.info(f"\nScored Actions ({len(scored_actions)} total):")
        for i, scored in enumerate(scored_actions[:5]):  # Show top 5
            try:
                if hasattr(scored, 'action_type'):
                    score_val = getattr(scored, 'score', 0)
                    action_type = getattr(scored, 'action_type', 'unknown')
                    label = getattr(scored, 'label', 'N/A')
                    logger.info(f"  [{i+1}] [{score_val:.1f}] {action_type} '{label}'")
                    text = getattr(scored, 'text', None)
                    if text:
                        logger.info(f"      Text: '{text}'")
                elif isinstance(scored, dict):
                    logger.info(f"  [{i+1}] [{scored.get('score', 0):.1f}] {scored.get('action_type', 'unknown')} '{scored.get('label', 'N/A')}'")
                    if scored.get('text'):
                        logger.info(f"      Text: '{scored.get('text')}'")
            except Exception as e:
                logger.info(f"  [{i+1}] (Error displaying action: {e})")
        if len(scored_actions) > 5:
            logger.info(f"  ... and {len(scored_actions) - 5} more")
    
    # Next action
    next_action = state.get('next_action')
    if next_action:
        try:
            if hasattr(next_action, 'action_type'):
                logger.info(f"\nNext Action: {getattr(next_action, 'action_type', 'unknown')} '{getattr(next_action, 'label', 'N/A')}' (score: {getattr(next_action, 'score', 0):.1f})")
                logger.info(f"  Selector: {getattr(next_action, 'selector', 'N/A')}")
                text = getattr(next_action, 'text', None)
                if text:
                    logger.info(f"  Text: '{text}'")
                reasoning = getattr(next_action, 'reasoning', 'N/A')
                logger.info(f"  Reasoning: {reasoning}")
            elif isinstance(next_action, dict):
                logger.info(f"\nNext Action: {next_action.get('action_type', 'unknown')} '{next_action.get('label', 'N/A')}' (score: {next_action.get('score', 0):.1f})")
                logger.info(f"  Selector: {next_action.get('selector', 'N/A')}")
                if next_action.get('text'):
                    logger.info(f"  Text: '{next_action.get('text')}'")
                logger.info(f"  Reasoning: {next_action.get('reasoning', 'N/A')}")
        except Exception as e:
            logger.info(f"\nNext Action: (Error displaying: {e})")
    
    # Errors list
    errors = state.get('errors', [])
    if errors:
        logger.info(f"\nErrors List ({len(errors)}):")
        for error in errors:
            logger.info(f"  - {error}")
    
    # Tried actions by URL (anti-loop memory)
    tried_by_url = state.get('tried_actions_by_url', {})
    if tried_by_url:
        logger.info(f"\nTried Actions by URL ({len(tried_by_url)} URLs):")
        for url, actions in tried_by_url.items():
            logger.info(f"  {url[:60]}...: {len(actions)} actions tried")
    
    # Interactable elements count
    interactables = state.get('interactable_elements', [])
    logger.info(f"\nInteractable Elements: {len(interactables)}")
    
    logger.info("=" * 60)
    logger.info("")

