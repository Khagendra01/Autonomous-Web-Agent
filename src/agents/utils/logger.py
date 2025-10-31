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

