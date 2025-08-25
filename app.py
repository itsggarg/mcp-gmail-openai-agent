"""
Flask Web Application for Gmail Agent

This module provides a web interface for users to interact with the Gmail agent
through REST API endpoints with proper asynchronous architecture.
"""
import os
import asyncio
import logging
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from agent import build_agent
from agents import Runner
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from functools import wraps
import threading
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask application
app = Flask(__name__)

# Configure CORS for API access
CORS(app)

# Configuration constants
USER_EMAIL = os.getenv('USER_EMAIL', 'user@gmail.com')
MAX_WORKERS = int(os.getenv('MAX_WORKERS', 5))
TASK_TIMEOUT = int(os.getenv('TASK_TIMEOUT', 60))
MAX_CONCURRENT_TASKS = int(os.getenv('MAX_CONCURRENT_TASKS', 10))

# Thread pool for running async tasks
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Task tracking for async operations
task_registry: Dict[str, Dict[str, Any]] = {}
registry_lock = threading.Lock()


class TaskStatus:
    """Enum for task statuses"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


def cleanup_old_tasks():
    """Remove completed tasks older than 5 minutes from registry"""
    with registry_lock:
        current_time = datetime.now()
        tasks_to_remove = []
        
        for task_id, task_info in task_registry.items():
            if task_info['status'] in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT]:
                if (current_time - task_info['updated_at']).seconds > 300:  # 5 minutes
                    tasks_to_remove.append(task_id)
        
        for task_id in tasks_to_remove:
            del task_registry[task_id]


def create_async_task(task_description: str) -> str:
    """
    Create a new async task and return its ID.
    
    Args:
        task_description: The task to execute
        
    Returns:
        str: Unique task ID
    """
    task_id = str(uuid.uuid4())
    
    with registry_lock:
        # Clean up old tasks periodically
        if len(task_registry) > MAX_CONCURRENT_TASKS * 2:
            cleanup_old_tasks()
        
        task_registry[task_id] = {
            'id': task_id,
            'description': task_description,
            'status': TaskStatus.PENDING,
            'result': None,
            'error': None,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
    
    # Submit task to executor
    future = executor.submit(run_async_task_with_tracking, task_id, task_description)
    
    # Add timeout handling
    def handle_timeout():
        try:
            future.result(timeout=TASK_TIMEOUT)
        except FutureTimeoutError:
            with registry_lock:
                if task_id in task_registry and task_registry[task_id]['status'] == TaskStatus.RUNNING:
                    task_registry[task_id]['status'] = TaskStatus.TIMEOUT
                    task_registry[task_id]['error'] = f'Task execution timed out after {TASK_TIMEOUT} seconds'
                    task_registry[task_id]['updated_at'] = datetime.now()
            future.cancel()
    
    # Start timeout handler in background
    threading.Thread(target=handle_timeout, daemon=True).start()
    
    return task_id


def run_async_task_with_tracking(task_id: str, task_description: str):
    """
    Run async task with status tracking.
    
    Args:
        task_id: Unique task identifier
        task_description: The task to execute
    """
    # Update status to running
    with registry_lock:
        if task_id in task_registry:
            task_registry[task_id]['status'] = TaskStatus.RUNNING
            task_registry[task_id]['updated_at'] = datetime.now()
    
    # Create new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(execute_agent_task(task_description))
        
        with registry_lock:
            if task_id in task_registry:
                if result['success']:
                    task_registry[task_id]['status'] = TaskStatus.COMPLETED
                    task_registry[task_id]['result'] = result['result']
                else:
                    task_registry[task_id]['status'] = TaskStatus.FAILED
                    task_registry[task_id]['error'] = result['error']
                task_registry[task_id]['updated_at'] = datetime.now()
                
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {str(e)}")
        with registry_lock:
            if task_id in task_registry:
                task_registry[task_id]['status'] = TaskStatus.FAILED
                task_registry[task_id]['error'] = str(e)
                task_registry[task_id]['updated_at'] = datetime.now()
    finally:
        loop.close()


async def execute_agent_task(task: str) -> Dict[str, Any]:
    """
    Execute the agent task asynchronously.
    
    This function handles the complete lifecycle of an agent task:
    1. Build the agent and MCP server
    2. Connect to the MCP server
    3. Execute the task
    4. Clean up resources
    
    Args:
        task: The task description to execute
        
    Returns:
        dict: Result dictionary containing:
            - success (bool): Whether the task completed successfully
            - result (str): The task output (if successful)
            - error (str): Error message (if failed)
    """
    agent = None
    mcp_server = None
    
    try:
        # Build agent and establish MCP connection
        agent, mcp_server = build_agent()
        await mcp_server.connect()
        logger.info(f"Executing task: {task[:100]}...")  # Log first 100 chars
        
        # Execute the task with internal timeout
        result = await asyncio.wait_for(
            Runner.run(agent, task),
            timeout=TASK_TIMEOUT - 5  # Leave 5 seconds buffer
        )
        
        logger.info("Task completed successfully")
        return {
            'success': True,
            'result': result.final_output
        }
        
    except asyncio.TimeoutError:
        logger.error(f"Task execution timed out")
        return {
            'success': False,
            'error': 'Task execution timed out'
        }
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Ensure cleanup happens even if an error occurs
        if mcp_server:
            try:
                await mcp_server.cleanup()
            except Exception as e:
                logger.error(f"Error during cleanup: {str(e)}")


@app.route('/')
def index():
    """
    Render the main application page.
    
    Returns:
        str: Rendered HTML template with user email
    """
    logger.info(f"Serving index page for user: {USER_EMAIL}")
    return render_template('index.html', user_email=USER_EMAIL)


@app.route('/api/execute-task', methods=['POST'])
def execute_task():
    """
    API endpoint to execute Gmail agent tasks asynchronously.
    
    This endpoint immediately returns a task ID and processes the task
    in the background, achieving non-blocking execution.
    
    Expects JSON payload with 'task' field.
    
    Returns:
        JSON response with:
            - success (bool): Whether the task was accepted
            - task_id (str): Unique identifier for tracking the task
            - message (str): Status message
            
    Status Codes:
        202: Accepted (task queued for processing)
        400: Bad request (missing task)
        503: Service unavailable (too many concurrent tasks)
    """
    try:
        # Validate request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON payload'}), 400
        
        task = data.get('task', '').strip()
        if not task:
            return jsonify({'error': 'Task is required'}), 400
        
        # Check concurrent task limit
        with registry_lock:
            active_tasks = sum(1 for t in task_registry.values() 
                             if t['status'] in [TaskStatus.PENDING, TaskStatus.RUNNING])
            if active_tasks >= MAX_CONCURRENT_TASKS:
                return jsonify({
                    'error': 'Too many concurrent tasks. Please try again later.'
                }), 503
        
        # Log task request
        logger.info(f"Received task request for user: {USER_EMAIL}")
        
        # Create async task
        task_id = create_async_task(task)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Task accepted and processing',
            'status_url': f'/api/task-status/{task_id}'
        }), 202
        
    except Exception as e:
        logger.error(f"Unexpected error in execute_task: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


@app.route('/api/task-status/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """
    Get the status of an async task.
    
    Args:
        task_id: The unique task identifier
        
    Returns:
        JSON response with task status and result (if completed)
        
    Status Codes:
        200: Success
        404: Task not found
    """
    with registry_lock:
        task_info = task_registry.get(task_id)
        
    if not task_info:
        return jsonify({'error': 'Task not found'}), 404
    
    response = {
        'task_id': task_id,
        'status': task_info['status'],
        'created_at': task_info['created_at'].isoformat(),
        'updated_at': task_info['updated_at'].isoformat(),
        'user_email': USER_EMAIL
    }
    
    if task_info['status'] == TaskStatus.COMPLETED:
        response['result'] = task_info['result']
    elif task_info['status'] in [TaskStatus.FAILED, TaskStatus.TIMEOUT]:
        response['error'] = task_info['error']
    
    return jsonify(response)


@app.route('/api/execute-task-sync', methods=['POST'])
def execute_task_sync():
    """
    Synchronous API endpoint for backward compatibility.
    
    This endpoint waits for task completion before returning.
    Use /api/execute-task for better performance.
    
    Returns:
        JSON response with task result
    """
    try:
        # Validate request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON payload'}), 400
        
        task = data.get('task', '').strip()
        if not task:
            return jsonify({'error': 'Task is required'}), 400
        
        # Create and wait for task
        task_id = create_async_task(task)
        
        # Poll for completion (with timeout)
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < TASK_TIMEOUT:
            with registry_lock:
                task_info = task_registry.get(task_id)
            
            if task_info and task_info['status'] in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT]:
                if task_info['status'] == TaskStatus.COMPLETED:
                    return jsonify({
                        'success': True,
                        'result': task_info['result'],
                        'user_email': USER_EMAIL
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': task_info['error']
                    }), 500
            
            # Wait before next poll
            asyncio.run(asyncio.sleep(0.5))
        
        return jsonify({
            'success': False,
            'error': 'Task execution timed out'
        }), 500
        
    except Exception as e:
        logger.error(f"Unexpected error in execute_task_sync: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


@app.route('/health')
def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    
    Returns:
        JSON response with service status and metrics
    """
    with registry_lock:
        active_tasks = sum(1 for t in task_registry.values() 
                         if t['status'] in [TaskStatus.PENDING, TaskStatus.RUNNING])
        total_tasks = len(task_registry)
    
    return jsonify({
        'status': 'healthy',
        'service': 'mcp-gmail-agent',
        'version': os.getenv('APP_VERSION', '1.0.0'),
        'metrics': {
            'active_tasks': active_tasks,
            'total_tracked_tasks': total_tasks,
            'max_concurrent_tasks': MAX_CONCURRENT_TASKS
        }
    }), 200


@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with JSON response."""
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with JSON response."""
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    # Production configuration
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting Gmail Agent API on port {port}")
    logger.info(f"Configured for user: {USER_EMAIL}")
    logger.info(f"Max concurrent tasks: {MAX_CONCURRENT_TASKS}")
    
    # Note: In production, use a proper WSGI server like Gunicorn
    # This direct Flask run should only be used for development
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True
    )
