# app.py - Frontend on Render.com
import eventlet
eventlet.monkey_patch()

# app.py - Frontend on Render.com
import os
import time
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO
import requests

# Use eventlet as the async mode for Render
async_mode = 'eventlet'
app = Flask(__name__)
# Get SECRET_KEY from environment variables
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
socketio = SocketIO(app, async_mode=async_mode, max_http_buffer_size=50 * 1024 * 1024)

# Get RunPod API details from Render's Environment Variables
RUNPOD_API_KEY = os.environ.get('RUNPOD_API_KEY')
RUNPOD_ENDPOINT_ID = os.environ.get('RUNPOD_ENDPOINT_ID')
RUNPOD_RUN_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run"
RUNPOD_STATUS_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status"


@app.route('/')
def index():
    """Serve the main index.html file."""
    return render_template('index.html') #

# This is the /download_template endpoint from your original app_cuda.py
# We move it here so the frontend can handle it without calling the GPU.
@app.route('/download_template/<num_nails>/<radius_cm>')
def download_template(num_nails, radius_cm):
    """Generate and download printable template PDF"""
    # We'll need to copy the PDF helper functions here.
    # For now, let's just return a placeholder.
    # We can add the full PDF generation code later if you want.
    try:
        num_nails = int(num_nails)
        radius_cm = float(radius_cm)
        # Placeholder: We will add the PDF code later.
        # For now, it just confirms the route works.
        return f"Template for {num_nails} nails and {radius_cm}cm radius. (PDF generation logic to be added)"
    except Exception as e:
        return str(e), 500

@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")

@socketio.on('wake_gpu')
def handle_wake_gpu():
    """Sends a quick health check to RunPod to potentially start a worker."""
    sid = request.sid
    print(f"⚡ Received wake_gpu request from {sid[:8]}...")

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("❌ Cannot wake GPU: Missing RunPod environment variables.")
        # Don't necessarily need to inform the user, just log it.
        return

    headers = { "Authorization": f"Bearer {RUNPOD_API_KEY}", "Content-Type": "application/json" }
    payload = { "input": { "endpoint": "health" } } # Use the fast health check

    try:
        # Send the request but don't wait long for a response
        # The goal is just to trigger the endpoint
        response = requests.post(RUNPOD_RUN_URL, headers=headers, json=payload, timeout=5) # 5 second timeout
        if response.status_code == 200:
            job_id = response.json().get('id', 'N/A')
            print(f"✅ Wake-up job submitted. Job ID: {job_id}")
        else:
             print(f"⚠️ Wake-up call failed or timed out: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Error sending wake-up call: {e}")
    # No need to poll or return anything to the user here

@socketio.on('preprocess_image')
def handle_preprocess(data):
    """
    Handles pre-processing. For now, we'll just acknowledge.
    We can optimize this later to call a /preprocess endpoint.
    """
    print("Pre-processing request received... (skipping for now)")
    # Just tell the client it's "done" so they can click Generate
    socketio.emit('status', {'msg': '✅ Image loaded! Click Generate to start.'}, to=request.sid)

@socketio.on('cancel_generation')
def handle_cancel():
    """Handles cancellation (stub for now)"""
    print(f"🛑 Cancel requested for session {request.sid}")
    socketio.emit('status', {'msg': '🛑 Cancelling... (Feature in development)'}, to=request.sid)

@socketio.on('start_generation')
def handle_start_generation(data):
    """
    Called when the user clicks 'Generate'.
    This function will:
    1. Send the job to the RunPod GPU backend.
    2. Poll RunPod until the job is 'COMPLETED'.
    3. Send the final result back to the user.
    """
    sid = request.sid
    print(f"🚀 Received generation request from {sid[:8]}...")
    socketio.emit('status', {'msg': '🚀 Sending job to GPU server...'}, to=sid)

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("❌ ERROR: Missing RunPod environment variables on Render!")
        socketio.emit('status', {'msg': '❌ Server config error: Missing API keys.'}, to=sid)
        return

    # 1. --- Send Job to RunPod ---
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # [cite_start]This is the payload our runpod_handler.py expects [cite: 1]
    payload = {
        "input": {
            "endpoint": "generate",
            "imageData": data['imageData'],
            "params": data['params']
        }
    }

    try:
        # Give the job a 30-second timeout to submit
        response = requests.post(RUNPOD_RUN_URL, headers=headers, json=payload, timeout=30)
        response_json = response.json()

        if response.status_code != 200 or "id" not in response_json:
            print(f"❌ RunPod submission error: {response.text}")
            socketio.emit('status', {'msg': f'❌ GPU server error: {response_json.get("error")}'}, to=sid)
            return

        job_id = response_json['id']
        print(f"✅ Job submitted to RunPod. Job ID: {job_id}")
        socketio.emit('status', {'msg': '⏳ Job queued on GPU. Waiting for worker... (this can take 30-90s)'})
        socketio.emit('progress', {'percent': 5}) # Give some initial progress

    except Exception as e:
        print(f"❌ Failed to submit job: {e}")
        socketio.emit('status', {'msg': f'❌ Error connecting to GPU: {e}'}, to=sid)
        return

    # 2. --- Poll RunPod for Result ---
    job_status_url = f"{RUNPOD_STATUS_URL}/{job_id}"
    start_time = time.time()
    
    while True:
        try:
            # Wait 2 seconds between checks
            socketio.sleep(2)
            
            poll_response = requests.get(job_status_url, headers=headers, timeout=10)
            poll_json = poll_response.json()
            status = poll_json.get('status')
            
            print(f"  Polling Job {job_id}: {status}")

            if status == 'IN_QUEUE':
                socketio.emit('status', {'msg': '⏳ Job is in queue...'})
                socketio.emit('progress', {'percent': 10})
            
            elif status == 'IN_PROGRESS':
                socketio.emit('status', {'msg': '⚙️ Generating on GPU... This may take a minute.'})
                # Simulate progress since we don't get live updates
                elapsed = time.time() - start_time
                progress = min(15 + (elapsed * 1.5), 90) # Slow progress bar
                socketio.emit('progress', {'percent': progress})

            elif status == 'COMPLETED':
                print("✅ Job completed!")
                socketio.emit('status', {'msg': '✅ Generation complete! Sending result...'})
                socketio.emit('progress', {'percent': 100})
                
                # Send the final sequence to the browser!
                output = poll_json.get('output', {})
                
                if output.get('status') == 'success':
                    socketio.emit('final_sequence', output) #
                else:
                    error_msg = output.get('message', 'Unknown GPU error')
                    print(f"❌ Job completed but failed: {error_msg}")
                    socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'})

                break # Exit the loop

            elif status == 'FAILED':
                print(f"❌ Job failed: {poll_json}")
                error_msg = poll_json.get('output', {}).get('message', 'Unknown GPU error')
                socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'})
                break # Exit the loop
            
            # Timeout after 5 minutes
            if time.time() - start_time > 300:
                socketio.emit('status', {'msg': '❌ Error: Job timed out.'})
                break

        except Exception as e:
            print(f"❌ Polling error: {e}")
            socketio.emit('status', {'msg': '❌ Error checking job status.'})
            break

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print("Starting server...")
    # Use allow_unsafe_werkzeug=True for newer Flask/SocketIO versions
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)