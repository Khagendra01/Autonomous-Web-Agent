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

# Global driver client for screenshot streaming
driver_clients = {}


class TaskRunner:
    """Runs tasks in a separate thread and emits updates via socketio."""
    
    def __init__(self, task_id, instruction, socketio_instance):
        self.task_id = task_id
        self.instruction = instruction
        self.socketio = socketio_instance
        self.running = False
        self.thread = None
        
    def start(self):
        """Start the task in a background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run_task, daemon=True)
        self.thread.start()
        
    def _run_task(self):
        """Run the task and emit updates."""
        try:
            self.socketio.emit('task_status', {
                'task_id': self.task_id,
                'status': 'starting',
                'message': 'Initializing task...'
            }, room=self.task_id)
            
            # Start screenshot streaming in a separate thread
            screenshot_thread = threading.Thread(
                target=self._stream_screenshots,
                daemon=True
            )
            screenshot_thread.start()
            
            # Run the actual task
            success = run_task(
                instruction=self.instruction,
                max_steps=30,
                output_dir="captures"
            )
            
            self.running = False
            
            self.socketio.emit('task_status', {
                'task_id': self.task_id,
                'status': 'completed' if success else 'failed',
                'message': 'Task completed' if success else 'Task failed'
            }, room=self.task_id)
            
        except Exception as e:
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
    
    # Generate task ID
    task_id = str(uuid.uuid4())
    
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
        socketio.enter_room(request.sid, task_id)
        emit('joined', {'task_id': task_id, 'message': 'Joined task room'})
        print(f'Client {request.sid} joined task {task_id}')


@socketio.on('leave_task')
def handle_leave_task(data):
    """Leave a task room."""
    task_id = data.get('task_id')
    if task_id:
        socketio.leave_room(request.sid, task_id)
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

