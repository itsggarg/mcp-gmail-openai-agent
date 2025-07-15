import os
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from agent import build_agent
from agents import Runner
from dotenv import load_dotenv
import secrets

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(16))
CORS(app)

# Store the user email (in production, this would come from authentication)
DEFAULT_USER_EMAIL = "user@gmail.com"

@app.route('/')
def index():
    # Set user email in session if not already set
    if 'user_email' not in session:
        session['user_email'] = DEFAULT_USER_EMAIL
    return render_template('index.html', user_email=session['user_email'])

@app.route('/api/execute-task', methods=['POST'])
async def execute_task():
    try:
        data = request.get_json()
        task = data.get('task', '')
        
        if not task:
            return jsonify({'error': 'Task is required'}), 400
        
        # Build and run the agent
        agent, mcp_server = build_agent()
        
        try:
            await mcp_server.connect()
            result = await Runner.run(agent, task)
            
            return jsonify({
                'success': True,
                'result': result.final_output,
                'user_email': session.get('user_email', DEFAULT_USER_EMAIL)
            })
            
        finally:
            await mcp_server.cleanup()
            
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)