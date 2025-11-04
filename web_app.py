"""Flask web application for the autonomous web agent."""
import os
import sys
import base64
import threading
import uuid
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.agents.runner import run_task
from src.drivers.grpc_client import DriverClient

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Store active tasks
active_tasks = {}
task_status = {}
current_task_id = None  # Track the currently running task

# Global driver client for screenshot streaming
driver_clients = {}


class TaskRunner:
    """Runs tasks in a separate thread and emits updates via socketio."""
    
    def __init__(self, task_id, instruction, socketio_instance):
        self.task_id = task_id
        self.instruction = instruction
        self.socketio = socketio_instance
        self.running = False
        self.cancelled = False
        self.thread = None
        self.screenshot_thread = None
        self.storage_path = None  # Store path to task output directory
        self.log_path = None  # Store path to log file
        self.json_path = None  # Store path to JSON manifest
        
    def start(self):
        """Start the task in a background thread."""
        self.running = True
        self.cancelled = False
        self.thread = threading.Thread(target=self._run_task, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the task and shutdown browser."""
        if not self.running:
            return
        
        self.cancelled = True
        self.running = False
        
        # Close browser
        try:
            client = DriverClient()
            client.close()
        except Exception as e:
            print(f"Error closing browser: {e}")
        
        # Emit cancellation status
        self.socketio.emit('task_status', {
            'task_id': self.task_id,
            'status': 'cancelled',
            'message': 'Task cancelled by user'
        }, room=self.task_id)
        
    def _run_task(self):
        """Run the task and emit updates."""
        try:
            self.socketio.emit('task_status', {
                'task_id': self.task_id,
                'status': 'starting',
                'message': 'Initializing task...'
            }, room=self.task_id)
            
            # Start screenshot streaming in a separate thread
            self.screenshot_thread = threading.Thread(
                target=self._stream_screenshots,
                daemon=True
            )
            self.screenshot_thread.start()
            
            # Check if cancelled before starting
            if self.cancelled:
                self.running = False
                return
            
            # Run the actual task
            success = run_task(
                instruction=self.instruction,
                max_steps=30,
                output_dir="captures"
            )
            
            if not self.cancelled:
                self.running = False
                
                # Find the most recent task output directory
                import re
                from pathlib import Path
                captures_dir = Path("captures")
                if captures_dir.exists():
                    # Find the most recently created directory
                    task_dirs = []
                    for app_dir in captures_dir.iterdir():
                        if app_dir.is_dir():
                            for task_dir in app_dir.iterdir():
                                if task_dir.is_dir():
                                    for timestamp_dir in task_dir.iterdir():
                                        if timestamp_dir.is_dir():
                                            task_dirs.append(timestamp_dir)
                    
                    if task_dirs:
                        # Sort by modification time, most recent first
                        task_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        self.storage_path = str(task_dirs[0])
                        self.log_path = str(task_dirs[0] / "agent_log.txt")
                        self.json_path = str(task_dirs[0] / "index.json")
                        
                        # Update task status with paths
                        if self.task_id in task_status:
                            task_status[self.task_id]['storage_path'] = self.storage_path
                            task_status[self.task_id]['log_path'] = self.log_path
                            task_status[self.task_id]['json_path'] = self.json_path
                
                self.socketio.emit('task_status', {
                    'task_id': self.task_id,
                    'status': 'completed' if success else 'failed',
                    'message': 'Task completed' if success else 'Task failed',
                    'has_logs': self.log_path is not None,
                    'has_json': self.json_path is not None
                }, room=self.task_id)
            
        except Exception as e:
            if not self.cancelled:
                self.running = False
                self.socketio.emit('task_status', {
                    'task_id': self.task_id,
                    'status': 'error',
                    'message': str(e)
                }, room=self.task_id)
            
    def _stream_screenshots(self):
        """Continuously stream screenshots while task is running."""
        import time
        client = None
        screenshot_count = 0
        max_retries = 30  # Wait up to 60 seconds for driver to be ready
        retry_count = 0
        
        # Wait for driver to be ready
        while retry_count < max_retries and self.running:
            try:
                client = DriverClient()
                # Try to take a test screenshot
                _ = client.screenshot()
                break  # Driver is ready
            except Exception:
                retry_count += 1
                time.sleep(2)
                continue
        
        if not client:
            self.socketio.emit('task_status', {
                'task_id': self.task_id,
                'status': 'error',
                'message': 'Driver server not available. Please start it first: python -m src.drivers.grpc_playwright_server'
            }, room=self.task_id)
            return
        
        # Stream screenshots while task is running
        while self.running:
            try:
                # Take screenshot
                screenshot_bytes = client.screenshot()
                
                # Convert to base64
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                # Emit to client
                self.socketio.emit('browser_update', {
                    'task_id': self.task_id,
                    'screenshot': screenshot_b64,
                    'count': screenshot_count,
                    'timestamp': time.time()
                }, room=self.task_id)
                
                screenshot_count += 1
                
                # Wait before next screenshot (adjust frequency as needed)
                time.sleep(1)  # 1 screenshot per second
                
            except Exception as e:
                # If driver connection is lost, try to reconnect
                try:
                    client = DriverClient()
                except Exception:
                    # Driver is not available, wait and retry
                    time.sleep(2)
                    continue


@app.route('/')
def index():
    """Serve the main web interface."""
    return render_template('index.html')


@app.route('/api/tasks', methods=['POST'])
def create_task():
    """Create a new task."""
    data = request.json
    instruction = data.get('instruction', '')
    
    if not instruction:
        return jsonify({'error': 'Instruction is required'}), 400
    
    # Stop previous task if exists
    global current_task_id
    if current_task_id and current_task_id in active_tasks:
        try:
            active_tasks[current_task_id].stop()
            print(f"Stopped previous task: {current_task_id}")
        except Exception as e:
            print(f"Error stopping previous task: {e}")
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    current_task_id = task_id
    
    # Create and start task runner
    runner = TaskRunner(task_id, instruction, socketio)
    active_tasks[task_id] = runner
    task_status[task_id] = {
        'id': task_id,
        'instruction': instruction,
        'status': 'starting',
        'created_at': time.time()
    }
    
    runner.start()
    
    return jsonify({
        'task_id': task_id,
        'status': 'started',
        'message': 'Task started successfully'
    })


@app.route('/api/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """Get task status."""
    if task_id not in task_status:
        return jsonify({'error': 'Task not found'}), 404
    
    return jsonify(task_status[task_id])


@app.route('/api/tasks/<task_id>/stop', methods=['POST'])
def stop_task(task_id):
    """Stop a running task."""
    global current_task_id
    
    if task_id not in active_tasks:
        return jsonify({'error': 'Task not found'}), 404
    
    try:
        active_tasks[task_id].stop()
        if current_task_id == task_id:
            current_task_id = None
        return jsonify({
            'task_id': task_id,
            'status': 'stopped',
            'message': 'Task stopped successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/current/stop', methods=['POST'])
def stop_current_task():
    """Stop the currently running task."""
    global current_task_id
    
    if not current_task_id or current_task_id not in active_tasks:
        return jsonify({'error': 'No active task to stop'}), 404
    
    try:
        active_tasks[current_task_id].stop()
        current_task_id = None
        return jsonify({
            'status': 'stopped',
            'message': 'Current task stopped successfully'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<task_id>/logs', methods=['GET'])
def get_task_logs(task_id):
    """Get task logs."""
    if task_id not in task_status:
        return jsonify({'error': 'Task not found'}), 404
    
    task = task_status[task_id]
    log_path = task.get('log_path') or (active_tasks[task_id].log_path if task_id in active_tasks else None)
    
    if not log_path:
        # Try to find the most recent log
        from pathlib import Path
        captures_dir = Path("captures")
        if captures_dir.exists():
            task_dirs = []
            for app_dir in captures_dir.iterdir():
                if app_dir.is_dir():
                    for task_dir in app_dir.iterdir():
                        if task_dir.is_dir():
                            for timestamp_dir in task_dir.iterdir():
                                if timestamp_dir.is_dir():
                                    log_file = timestamp_dir / "agent_log.txt"
                                    if log_file.exists():
                                        task_dirs.append((log_file, timestamp_dir.stat().st_mtime))
            
            if task_dirs:
                task_dirs.sort(key=lambda x: x[1], reverse=True)
                log_path = str(task_dirs[0][0])
    
    if not log_path or not Path(log_path).exists():
        return jsonify({'error': 'Log file not found'}), 404
    
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            logs = f.read()
        return jsonify({
            'task_id': task_id,
            'log_path': log_path,
            'logs': logs
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks/<task_id>/json', methods=['GET'])
def get_task_json(task_id):
    """Get task JSON manifest."""
    if task_id not in task_status:
        return jsonify({'error': 'Task not found'}), 404
    
    task = task_status[task_id]
    json_path = task.get('json_path') or (active_tasks[task_id].json_path if task_id in active_tasks else None)
    
    if not json_path:
        # Try to find the most recent JSON
        from pathlib import Path
        import json as json_lib
        captures_dir = Path("captures")
        if captures_dir.exists():
            task_dirs = []
            for app_dir in captures_dir.iterdir():
                if app_dir.is_dir():
                    for task_dir in app_dir.iterdir():
                        if task_dir.is_dir():
                            for timestamp_dir in task_dir.iterdir():
                                if timestamp_dir.is_dir():
                                    json_file = timestamp_dir / "index.json"
                                    if json_file.exists():
                                        task_dirs.append((json_file, timestamp_dir.stat().st_mtime))
            
            if task_dirs:
                task_dirs.sort(key=lambda x: x[1], reverse=True)
                json_path = str(task_dirs[0][0])
    
    if not json_path or not Path(json_path).exists():
        return jsonify({'error': 'JSON file not found'}), 404
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json_lib.load(f)
        return jsonify({
            'task_id': task_id,
            'json_path': json_path,
            'data': data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    """List all tasks."""
    return jsonify(list(task_status.values()))


@socketio.on('connect')
def handle_connect():
    """Handle client connection."""
    print(f'Client connected: {request.sid}')


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection."""
    print(f'Client disconnected: {request.sid}')


@socketio.on('join_task')
def handle_join_task(data):
    """Join a task room for real-time updates."""
    task_id = data.get('task_id')
    if task_id:
        from flask_socketio import join_room
        join_room(task_id)
        emit('joined', {'task_id': task_id, 'message': 'Joined task room'})
        print(f'Client {request.sid} joined task {task_id}')


@socketio.on('leave_task')
def handle_leave_task(data):
    """Leave a task room."""
    task_id = data.get('task_id')
    if task_id:
        from flask_socketio import leave_room
        leave_room(task_id)
        emit('left', {'task_id': task_id, 'message': 'Left task room'})


if __name__ == '__main__':
    # Check if gRPC driver is running
    try:
        client = DriverClient()
        # Try to connect (this will fail if driver is not running)
        print("⚠️  Make sure the gRPC driver server is running:")
        print("   python -m src.drivers.grpc_playwright_server")
    except Exception as e:
        print(f"⚠️  Driver client check: {e}")
    
    # Run the Flask app
    print("\n" + "="*60)
    print("🌐 Starting Web Agent Server")
    print("="*60)
    print("📡 Server will be available at http://0.0.0.0:5000")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)

