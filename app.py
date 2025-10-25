# app.py - OPTIMIZED Frontend on Render.com
import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO
import requests

async_mode = 'eventlet'
app = Flask(__name__)
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
    return render_template('index.html')


@app.route('/download_template/<num_nails>/<radius_cm>')
def download_template(num_nails, radius_cm):
    """Generate and download printable template PDF"""
    try:
        num_nails = int(num_nails)
        radius_cm = float(radius_cm)
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
    """Sends a quick health check to RunPod to start a worker."""
    sid = request.sid
    print(f"⚡ Wake GPU request from {sid[:8]}...")

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("❌ Cannot wake GPU: Missing RunPod environment variables.")
        return

    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"input": {"endpoint": "health"}}

    try:
        response = requests.post(RUNPOD_RUN_URL, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            job_id = response.json().get('id', 'N/A')
            print(f"✅ Wake-up job submitted. Job ID: {job_id}")
        else:
            print(f"⚠️ Wake-up call failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error sending wake-up call: {e}")


@socketio.on('preprocess_image')
def handle_preprocess(data):
    """
    🚀 OPTIMIZED: Pre-process image and cache on GPU.
    This is THE KEY optimization - cache the expensive Radon transform!
    """
    sid = request.sid
    print(f"🔧 Preprocessing request from {sid[:8]}...")
    socketio.emit('status', {'msg': '⚙️ Pre-processing on GPU...'}, to=sid)
    
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("⚠️ No RunPod config, skipping preprocessing")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
        return
    
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Call preprocessing endpoint (fast, cacheable)
    payload = {
        "input": {
            "endpoint": "preprocess",
            "imageData": data['imageData'],
            "num_nails": data['params']['num_nails'],
            "image_resolution": data['params']['image_resolution']
        }
    }
    
    try:
        submit_start = time.time()
        response = requests.post(RUNPOD_RUN_URL, headers=headers, json=payload, timeout=30)
        response_json = response.json()
        
        if response.status_code != 200 or "id" not in response_json:
            print(f"⚠️ Preprocessing submit failed: {response.text}")
            socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
            return
        
        job_id = response_json['id']
        submit_time = time.time() - submit_start
        print(f"✅ Preprocessing job {job_id} submitted in {submit_time:.2f}s")
        socketio.emit('status', {'msg': '⏳ Warming GPU & caching data...'}, to=sid)
        
        # 🚀 OPTIMIZED: Adaptive polling
        job_status_url = f"{RUNPOD_STATUS_URL}/{job_id}"
        start_time = time.time()
        poll_count = 0
        
        while time.time() - start_time < 60:  # Max 60 seconds
            # Start with fast polling, slow down gradually
            if poll_count < 10:
                poll_interval = 0.5  # Fast for first 5 seconds
            elif poll_count < 20:
                poll_interval = 1.0  # Medium for next 10 seconds
            else:
                poll_interval = 2.0  # Slow after that
            
            socketio.sleep(poll_interval)
            poll_count += 1
            
            poll_response = requests.get(job_status_url, headers=headers, timeout=10)
            poll_json = poll_response.json()
            status = poll_json.get('status')
            elapsed = time.time() - start_time
            
            print(f"  Preprocess poll #{poll_count} ({elapsed:.1f}s): {status}")
            
            if status == 'COMPLETED':
                output = poll_json.get('output', {})
                if output.get('status') == 'success':
                    total_time = time.time() - submit_start
                    cached = output.get('cached', False)
                    cache_msg = "INSTANT (cached)" if cached else f"{total_time:.1f}s"
                    print(f"✅ Preprocessing complete in {cache_msg}")
                    socketio.emit('status', {
                        'msg': f'🚀 READY! Generate will be FAST (data cached on GPU)'
                    }, to=sid)
                    socketio.emit('preprocessing_complete', {
                        'cache_ready': True,
                        'time': total_time,
                        'cached': cached
                    }, to=sid)
                else:
                    print(f"⚠️ Preprocessing error: {output.get('message')}")
                    socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
                return
                
            elif status == 'FAILED':
                print(f"⚠️ Preprocessing failed: {poll_json}")
                socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
                return
        
        # Timeout - still allow generation
        print("⚠️ Preprocessing timed out")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
        
    except Exception as e:
        print(f"⚠️ Preprocessing error: {e}")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)


@socketio.on('cancel_generation')
def handle_cancel():
    """Handles cancellation (stub for now)"""
    print(f"🛑 Cancel requested for session {request.sid}")
    socketio.emit('status', {'msg': '🛑 Cancelling... (Feature in development)'}, to=request.sid)


@socketio.on('start_generation')
def handle_start_generation(data):
    """
    🚀 OPTIMIZED: Generation with adaptive polling and better progress tracking.
    """
    sid = request.sid
    print(f"🚀 Generation request from {sid[:8]}...")
    socketio.emit('status', {'msg': '🚀 Sending job to GPU server...'}, to=sid)

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("❌ ERROR: Missing RunPod environment variables on Render!")
        socketio.emit('status', {'msg': '❌ Server config error: Missing API keys.'}, to=sid)
        return

    # --- Send Job to RunPod ---
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "input": {
            "endpoint": "generate",
            "imageData": data['imageData'],
            "params": data['params']
        }
    }

    try:
        submit_start = time.time()
        response = requests.post(RUNPOD_RUN_URL, headers=headers, json=payload, timeout=30)
        response_json = response.json()

        if response.status_code != 200 or "id" not in response_json:
            print(f"❌ RunPod submission error: {response.text}")
            socketio.emit('status', {
                'msg': f'❌ GPU server error: {response_json.get("error")}'
            }, to=sid)
            return

        job_id = response_json['id']
        submit_time = time.time() - submit_start
        print(f"✅ Job {job_id} submitted in {submit_time:.2f}s")
        socketio.emit('status', {'msg': '⏳ Job queued on GPU...'}, to=sid)
        socketio.emit('progress', {'percent': 5}, to=sid)

    except Exception as e:
        print(f"❌ Failed to submit job: {e}")
        socketio.emit('status', {'msg': f'❌ Error connecting to GPU: {e}'}, to=sid)
        return

    # --- 🚀 OPTIMIZED: Adaptive Polling ---
    job_status_url = f"{RUNPOD_STATUS_URL}/{job_id}"
    start_time = time.time()
    poll_count = 0
    last_status = None
    
    while True:
        # Adaptive polling intervals based on poll count
        if poll_count < 10:
            poll_interval = 0.5  # Fast polling for first 5 seconds
        elif poll_count < 30:
            poll_interval = 1.0  # Medium polling for next 20 seconds
        else:
            poll_interval = 2.0  # Slow polling after that
        
        socketio.sleep(poll_interval)
        poll_count += 1
        
        try:
            poll_response = requests.get(job_status_url, headers=headers, timeout=10)
            poll_json = poll_response.json()
            status = poll_json.get('status')
            elapsed = time.time() - start_time
            
            # Only log status changes to reduce noise
            if status != last_status:
                print(f"  Poll #{poll_count} ({elapsed:.1f}s): {status}")
                last_status = status

            if status == 'IN_QUEUE':
                socketio.emit('status', {'msg': '⏳ Job queued...'}, to=sid)
                socketio.emit('progress', {'percent': 10}, to=sid)
            
            elif status == 'IN_PROGRESS':
                socketio.emit('status', {'msg': '⚙️ Generating on GPU...'}, to=sid)
                # Simulate progress based on elapsed time
                progress = min(15 + (elapsed * 2), 90)
                socketio.emit('progress', {'percent': progress}, to=sid)

            elif status == 'COMPLETED':
                total_time = time.time() - submit_start
                print(f"✅ Job completed in {total_time:.1f}s!")
                socketio.emit('status', {'msg': '✅ Generation complete!'}, to=sid)
                socketio.emit('progress', {'percent': 100}, to=sid)
                
                output = poll_json.get('output', {})
                
                if output.get('status') == 'success':
                    # Add timing info to output
                    output['total_time'] = total_time
                    output['poll_count'] = poll_count
                    socketio.emit('final_sequence', output, to=sid)
                else:
                    error_msg = output.get('message', 'Unknown GPU error')
                    print(f"❌ Job completed but failed: {error_msg}")
                    socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'}, to=sid)

                break  # Exit loop

            elif status == 'FAILED':
                print(f"❌ Job failed: {poll_json}")
                error_msg = poll_json.get('output', {}).get('message', 'Unknown GPU error')
                socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'}, to=sid)
                break
            
            # Timeout after 5 minutes
            if elapsed > 300:
                print(f"⏰ Job timed out after {elapsed:.0f}s")
                socketio.emit('status', {'msg': '❌ Error: Job timed out.'}, to=sid)
                break

        except Exception as e:
            print(f"❌ Polling error: {e}")
            socketio.emit('status', {'msg': '❌ Error checking job status.'}, to=sid)
            break


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print("\n" + "="*60)
    print("🎨 String Art Frontend (OPTIMIZED)")
    print("="*60)
    print(f"🌐 Server starting on port {port}")
    print(f"🔥 Optimizations: Preprocessing cache + Adaptive polling")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)