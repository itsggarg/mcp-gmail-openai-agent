import os
import asyncio
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from agent import build_agent
from agents import Runner
from dotenv import load_dotenv
import secrets
from concurrent.futures import ThreadPoolExecutor
import nest_asyncio

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))
CORS(app)

# Store the user email (in production, this would come from authentication)
DEFAULT_USER_EMAIL = "user@gmail.com"

# Thread pool for running async tasks
executor = ThreadPoolExecutor(max_workers=5)

def run_async_task(task):
    """Run async task in a new event loop"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(execute_agent_task(task))
    finally:
        loop.close()

async def execute_agent_task(task):
    """Execute the agent task"""
    agent, mcp_server = build_agent()
    try:
        await mcp_server.connect()
        result = await Runner.run(agent, task)
        return {
            'success': True,
            'result': result.final_output
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        await mcp_server.cleanup()

@app.route('/')
def index():
    # Set user email in session if not already set
    if 'user_email' not in session:
        session['user_email'] = DEFAULT_USER_EMAIL
    return render_template('index.html', user_email=session['user_email'])

@app.route('/api/execute-task', methods=['POST'])
def execute_task():
    try:
        data = request.get_json()
        task = data.get('task', '')
        
        if not task:
            return jsonify({'error': 'Task is required'}), 400
        
        # Run the async task in a thread
        future = executor.submit(run_async_task, task)
        result = future.result(timeout=60)  # 60 second timeout
        
        if result['success']:
            return jsonify({
                'success': True,
                'result': result['result'],
                'user_email': session.get('user_email', DEFAULT_USER_EMAIL)
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Unknown error')
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/user-info', methods=['GET'])
def get_user_info():
    return jsonify({
        'email': session.get('user_email', DEFAULT_USER_EMAIL)
    })

@app.route('/health')
def health_check():
    """Health check endpoint for Render"""
    return jsonify({
        'status': 'healthy',
        'service': 'mcp-gmail-agent'
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
