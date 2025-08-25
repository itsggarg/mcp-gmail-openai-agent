"""
Flask Web Application for Gmail Agent

This module provides a web interface for users to interact with the Gmail agent
through REST API endpoints.
"""
import os
import asyncio
import logging
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from agent import build_agent
from agents import Runner
from dotenv import load_dotenv
import secrets
from concurrent.futures import ThreadPoolExecutor
import nest_asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Apply nest_asyncio to allow nested event loops in Flask
nest_asyncio.apply()

# Load environment variables
load_dotenv()

# Initialize Flask application
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))

# Configure CORS for API access
CORS(app)

# Configuration constants
DEFAULT_USER_EMAIL = os.getenv('DEFAULT_USER_EMAIL', 'user@gmail.com')
MAX_WORKERS = int(os.getenv('MAX_WORKERS', 5))
TASK_TIMEOUT = int(os.getenv('TASK_TIMEOUT', 60))

# Thread pool for running async tasks
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)


def run_async_task(task):
    """
    Run async task in a new event loop.
    
    This function creates a new event loop to execute async tasks
    within Flask's synchronous context.
    
    Args:
        task (str): The task description to execute
        
    Returns:
        dict: Result dictionary with 'success' and either 'result' or 'error'
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(execute_agent_task(task))
    finally:
        loop.close()


async def execute_agent_task(task):
    """
    Execute the agent task asynchronously.
    
    This function handles the complete lifecycle of an agent task:
    1. Build the agent and MCP server
    2. Connect to the MCP server
    3. Execute the task
    4. Clean up resources
    
    Args:
        task (str): The task description to execute
        
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
        
        # Execute the task
        result = await Runner.run(agent, task)
        
        logger.info("Task completed successfully")
        return {
            'success': True,
            'result': result.final_output
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
            await mcp_server.cleanup()


@app.route('/')
def index():
    """
    Render the main application page.
    
    Sets user email in session if not already present.
    
    Returns:
        str: Rendered HTML template
    """
    if 'user_email' not in session:
        session['user_email'] = DEFAULT_USER_EMAIL
        logger.info(f"New session created for user: {DEFAULT_USER_EMAIL}")
    
    return render_template('index.html', user_email=session['user_email'])


@app.route('/api/execute-task', methods=['POST'])
def execute_task():
    """
    API endpoint to execute Gmail agent tasks.
    
    Expects JSON payload with 'task' field.
    
    Returns:
        JSON response with:
            - success (bool): Whether the task completed successfully
            - result (str): Task output (if successful)
            - error (str): Error message (if failed)
            - user_email (str): Current user's email
            
    Status Codes:
        200: Success
        400: Bad request (missing task)
        500: Internal server error
    """
    try:
        # Validate request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON payload'}), 400
            
        task = data.get('task', '').strip()
        if not task:
            return jsonify({'error': 'Task is required'}), 400
        
        # Log task request
        logger.info(f"Received task request from {session.get('user_email', 'unknown')}")
        
        # Execute task asynchronously with timeout
        future = executor.submit(run_async_task, task)
        result = future.result(timeout=TASK_TIMEOUT)
        
        # Return appropriate response
        if result['success']:
            return jsonify({
                'success': True,
                'result': result['result'],
                'user_email': session.get('user_email', DEFAULT_USER_EMAIL)
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error occurred')
            }), 500
            
    except TimeoutError:
        logger.error(f"Task timeout after {TASK_TIMEOUT} seconds")
        return jsonify({
            'success': False,
            'error': f'Task execution timed out after {TASK_TIMEOUT} seconds'
        }), 500
        
    except Exception as e:
        logger.error(f"Unexpected error in execute_task: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred'
        }), 500


@app.route('/api/user-info', methods=['GET'])
def get_user_info():
    """
    Get current user information.
    
    Returns:
        JSON response with user email
    """
    return jsonify({
        'email': session.get('user_email', DEFAULT_USER_EMAIL)
    })


@app.route('/health')
def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    
    Returns:
        JSON response with service status
    """
    return jsonify({
        'status': 'healthy',
        'service': 'mcp-gmail-agent',
        'version': os.getenv('APP_VERSION', '1.0.0')
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
    
    # Note: In production, use a proper WSGI server like Gunicorn
    # This direct Flask run should only be used for development
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True
    )
