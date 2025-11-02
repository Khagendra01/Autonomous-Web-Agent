"""Real-time logging utility for agent execution."""
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class AgentLogger:
    """Logger that writes to file in real-time (instant flush)."""
    
    def __init__(self, log_file_path: str):
        """Initialize logger with log file path."""
        self.log_file_path = Path(log_file_path)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = None
        self._ensure_file()
    
    def _ensure_file(self):
        """Ensure log file is open."""
        if self.log_file is None or self.log_file.closed:
            self.log_file = open(self.log_file_path, 'a', encoding='utf-8')
            # Write header if file is new
            if self.log_file.tell() == 0:
                self.log_file.write(f"{'='*80}\n")
                self.log_file.write(f"Agent Execution Log - Started: {datetime.now().isoformat()}\n")
                self.log_file.write(f"{'='*80}\n\n")
                self.log_file.flush()
    
    def log(self, message: str, level: str = "INFO"):
        """Log a message with instant flush."""
        self._ensure_file()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_line = f"[{timestamp}] [{level}] {message}\n"
        self.log_file.write(log_line)
        self.log_file.flush()  # Instant flush for real-time viewing
        os.fsync(self.log_file.fileno())  # Force write to disk
    
    def log_section(self, title: str, content: str = ""):
        """Log a section with title and optional content."""
        self.log(f"\n{'='*80}", "SECTION")
        self.log(f"{title}", "SECTION")
        self.log(f"{'='*80}", "SECTION")
        if content:
            self.log(content, "SECTION")
    
    def log_dict(self, title: str, data: dict, level: str = "INFO"):
        """Log a dictionary in a readable format."""
        self.log(f"{title}:", level)
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                import json
                self.log(f"  {key}: {json.dumps(value, indent=4)}", level)
            else:
                self.log(f"  {key}: {value}", level)
    
    def log_list(self, title: str, items: list, level: str = "INFO"):
        """Log a list in a readable format."""
        self.log(f"{title} ({len(items)} items):", level)
        for i, item in enumerate(items, 1):
            if isinstance(item, dict):
                import json
                self.log(f"  {i}. {json.dumps(item, indent=4)}", level)
            else:
                self.log(f"  {i}. {item}", level)
    
    def close(self):
        """Close the log file."""
        if self.log_file and not self.log_file.closed:
            self.log_file.write(f"\n{'='*80}\n")
            self.log_file.write(f"Log ended: {datetime.now().isoformat()}\n")
            self.log_file.write(f"{'='*80}\n")
            self.log_file.flush()
            self.log_file.close()
    
    def __del__(self):
        """Ensure file is closed on destruction."""
        self.close()


# Global logger instance
_global_logger: Optional[AgentLogger] = None


def get_logger() -> Optional[AgentLogger]:
    """Get the global logger instance."""
    return _global_logger


def init_logger(log_file_path: str) -> AgentLogger:
    """Initialize the global logger."""
    global _global_logger
    _global_logger = AgentLogger(log_file_path)
    return _global_logger


def set_logger(logger: AgentLogger):
    """Set the global logger instance."""
    global _global_logger
    _global_logger = logger

