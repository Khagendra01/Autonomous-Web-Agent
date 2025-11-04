"""Comprehensive logging utility for agent debugging."""
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


class AgentLogger:
    """Logger that writes to both console and file."""
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self.log_buffer = []
        self.start_time = datetime.now()
        
        if log_file:
            # Ensure directory exists
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Clear existing log or create new
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"=== Agent Log Session Started: {self.start_time.isoformat()} ===\n\n")
    
    def _write(self, level: str, message: str, data: Optional[dict] = None):
        """Write log entry to both console and file."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        prefix = f"[{timestamp}] [{level}]"
        
        # Format message
        if data:
            formatted = f"{prefix} {message}\n{self._format_data(data)}\n"
        else:
            formatted = f"{prefix} {message}\n"
        
        # Write to console
        print(formatted, end='')
        
        # Write to file
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(formatted)
            except Exception as e:
                print(f"[ERROR] Failed to write to log file: {e}", file=sys.stderr)
    
    def _format_data(self, data: dict, indent: int = 2) -> str:
        """Format data dictionary for logging."""
        try:
            return json.dumps(data, indent=indent, default=str, ensure_ascii=False)
        except Exception:
            return str(data)
    
    def debug(self, message: str, data: Optional[dict] = None):
        """Log debug message."""
        self._write("DEBUG", message, data)
    
    def info(self, message: str, data: Optional[dict] = None):
        """Log info message."""
        self._write("INFO", message, data)
    
    def warning(self, message: str, data: Optional[dict] = None):
        """Log warning message."""
        self._write("WARN", message, data)
    
    def error(self, message: str, data: Optional[dict] = None):
        """Log error message."""
        self._write("ERROR", message, data)
    
    def cdp(self, message: str, data: Optional[dict] = None):
        """Log CDP-specific message."""
        self._write("CDP", message, data)
    
    def llm(self, message: str, data: Optional[dict] = None):
        """Log LLM-related message."""
        self._write("LLM", message, data)
    
    def label(self, message: str, data: Optional[dict] = None):
        """Log label extraction message."""
        self._write("LABEL", message, data)
    
    def section(self, title: str):
        """Write a section header."""
        separator = "=" * 80
        formatted = f"\n{separator}\n{title}\n{separator}\n"
        
        print(formatted, end='')
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(formatted)
            except Exception:
                pass
    
    def close(self):
        """Close the log file."""
        if self.log_file:
            end_time = datetime.now()
            duration = end_time - self.start_time
            footer = f"\n=== Agent Log Session Ended: {end_time.isoformat()} (Duration: {duration}) ===\n"
            
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    f.write(footer)
            except Exception:
                pass


# Global logger instance
_logger: Optional[AgentLogger] = None


def init_logger(log_file: Optional[str] = None):
    """Initialize the global logger."""
    global _logger
    _logger = AgentLogger(log_file)
    return _logger


def get_logger() -> AgentLogger:
    """Get the global logger instance."""
    global _logger
    if _logger is None:
        _logger = AgentLogger()  # Default logger without file
    return _logger

