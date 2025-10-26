# app.py - Frontend with GPU Router (Home GPU + RunPod Failover)
import eventlet
eventlet.monkey_patch()

import os
import time
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO
import requests

# Import our GPU router
from gpu_router import GPURouter

async_mode = 'eventlet'
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
socketio = SocketIO(app, async_mode=async_mode, max_http_buffer_size=50 * 1024 * 1024)

# Get configuration from environment variables
RUNPOD_API_KEY = os.environ.get('RUNPOD_API_KEY')
RUNPOD_ENDPOINT_ID = os.environ.get('RUNPOD_ENDPOINT_ID')
HOME_GPU_URL = os.environ.get('HOME_GPU_URL')  # NEW: Tailscale URL like http://100.x.x.x:8001

RUNPOD_RUN_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run"
RUNPOD_STATUS_URL = f"https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/status"

# Initialize GPU Router
gpu_router = GPURouter(
    home_gpu_url=HOME_GPU_URL,
    runpod_run_url=RUNPOD_RUN_URL,
    runpod_status_url=RUNPOD_STATUS_URL,
    runpod_api_key=RUNPOD_API_KEY
)


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


@app.route('/gpu-stats')
def gpu_stats():
    """Get GPU router statistics"""
    return gpu_router.get_stats()


@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")


@socketio.on('wake_gpu')
def handle_wake_gpu():
    """Sends a quick health check to wake up GPUs"""
    sid = request.sid
    print(f"⚡ Wake GPU request from {sid[:8]}...")

    # Check home GPU first
    if gpu_router.check_home_gpu_health():
        print(f"✅ Home GPU is awake and ready")
        socketio.emit('status', {'msg': '✅ Home GPU ready!'}, to=sid)
        return
    
    # Wake RunPod if home GPU not available
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("⚠️ Cannot wake RunPod: Missing environment variables")
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
            print(f"✅ RunPod wake-up job submitted. Job ID: {job_id}")
            socketio.emit('status', {'msg': '✅ RunPod waking up...'}, to=sid)
        else:
            print(f"⚠️ Wake-up call failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Error sending wake-up call: {e}")


@socketio.on('preprocess_image')
def handle_preprocess(data):
    """
    🚀 OPTIMIZED: Pre-process image using GPU router (tries home GPU first)
    """
    sid = request.sid
    print(f"🔧 Preprocessing request from {sid[:8]}...")
    socketio.emit('status', {'msg': '⚙️ Pre-processing...'}, to=sid)
    
    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("⚠️ No RunPod config and no home GPU")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
        return
    
    try:
        submit_start = time.time()
        
        # Use GPU router to try home GPU first, then RunPod
        result, provider = gpu_router.preprocess(
            image_data=data['imageData'],
            num_nails=data['params']['num_nails'],
            image_resolution=data['params']['image_resolution']
        )
        
        # If home GPU was used (synchronous), we're done!
        if provider == "home":
            total_time = time.time() - submit_start
            cached = result.get('cached', False)
            cache_msg = "INSTANT (cached)" if cached else f"{total_time:.1f}s"
            print(f"✅ Home GPU preprocessing complete in {cache_msg}")
            socketio.emit('status', {
                'msg': f'🚀 READY! Using Home GPU (data cached)'
            }, to=sid)
            socketio.emit('preprocessing_complete', {
                'cache_ready': True,
                'time': total_time,
                'cached': cached,
                'provider': 'home'
            }, to=sid)
            return
        
        # RunPod path - need to poll
        if "id" not in result:
            print(f"⚠️ RunPod preprocessing failed: {result}")
            socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
            return
        
        job_id = result['id']
        submit_time = time.time() - submit_start
        print(f"✅ RunPod preprocessing job {job_id} submitted in {submit_time:.2f}s")
        socketio.emit('status', {'msg': '⏳ Processing on RunPod...'}, to=sid)
        
        # Poll RunPod for completion
        headers = {
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
            "Content-Type": "application/json"
        }
        
        job_status_url = f"{RUNPOD_STATUS_URL}/{job_id}"
        start_time = time.time()
        poll_count = 0
        
        while time.time() - start_time < 60:
            if poll_count < 10:
                poll_interval = 0.5
            elif poll_count < 20:
                poll_interval = 1.0
            else:
                poll_interval = 2.0
            
            socketio.sleep(poll_interval)
            poll_count += 1
            
            poll_response = requests.get(job_status_url, headers=headers, timeout=10)
            poll_json = poll_response.json()
            status = poll_json.get('status')
            
            if status == 'COMPLETED':
                output = poll_json.get('output', {})
                if output.get('status') == 'success':
                    total_time = time.time() - submit_start
                    print(f"✅ RunPod preprocessing complete in {total_time:.1f}s")
                    socketio.emit('status', {
                        'msg': f'🚀 READY! RunPod cached (data ready)'
                    }, to=sid)
                    socketio.emit('preprocessing_complete', {
                        'cache_ready': True,
                        'time': total_time,
                        'cached': False,
                        'provider': 'runpod'
                    }, to=sid)
                else:
                    print(f"⚠️ RunPod preprocessing error: {output.get('message')}")
                    socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
                return
                
            elif status == 'FAILED':
                print(f"⚠️ RunPod preprocessing failed: {poll_json}")
                socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
                return
        
        print("⚠️ RunPod preprocessing timed out")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)
        
    except Exception as e:
        print(f"⚠️ Preprocessing error: {e}")
        socketio.emit('status', {'msg': '✅ Image loaded! Click Generate.'}, to=sid)


@socketio.on('cancel_generation')
def handle_cancel():
    """Handles cancellation (stub for now)"""
    print(f"🛑 Cancel requested for session {request.sid}")
    socketio.emit('status', {'msg': '🛑 Cancelling...'}, to=request.sid)


@socketio.on('start_generation')
def handle_start_generation(data):
    """
    🚀 OPTIMIZED: Generation using GPU router (tries home GPU first, falls back to RunPod)
    """
    sid = request.sid
    print(f"🚀 Generation request from {sid[:8]}...")
    socketio.emit('status', {'msg': '🚀 Starting generation...'}, to=sid)

    if not RUNPOD_API_KEY or not RUNPOD_ENDPOINT_ID:
        print("❌ ERROR: Missing RunPod environment variables!")
        socketio.emit('status', {'msg': '❌ Server config error: Missing API keys.'}, to=sid)
        return

    try:
        submit_start = time.time()
        
        # Use GPU router - tries home GPU first, then RunPod
        result, provider = gpu_router.generate(
            image_data=data['imageData'],
            params=data['params']
        )
        
        # If home GPU was used (synchronous), we're done!
        if provider == "home":
            total_time = time.time() - submit_start
            print(f"✅ Home GPU generation complete in {total_time:.1f}s!")
            
            socketio.emit('status', {'msg': '✅ Generation complete!'}, to=sid)
            socketio.emit('progress', {'percent': 100}, to=sid)
            
            # Add timing info
            result['total_time'] = total_time
            result['provider'] = 'home'
            socketio.emit('final_sequence', result, to=sid)
            return
        
        # RunPod path - need to poll
        if "id" not in result:
            print(f"❌ RunPod submission error: {result}")
            socketio.emit('status', {
                'msg': f'❌ GPU server error: {result.get("error")}'
            }, to=sid)
            return

        job_id = result['id']
        submit_time = time.time() - submit_start
        print(f"✅ RunPod job {job_id} submitted in {submit_time:.2f}s")
        socketio.emit('status', {'msg': '⏳ Job queued on RunPod...'}, to=sid)
        socketio.emit('progress', {'percent': 5}, to=sid)

    except Exception as e:
        print(f"❌ Failed to submit job: {e}")
        socketio.emit('status', {'msg': f'❌ Error: {e}'}, to=sid)
        return

    # Poll RunPod for completion
    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json"
    }
    
    job_status_url = f"{RUNPOD_STATUS_URL}/{job_id}"
    start_time = time.time()
    poll_count = 0
    last_status = None
    
    while True:
        if poll_count < 10:
            poll_interval = 0.5
        elif poll_count < 30:
            poll_interval = 1.0
        else:
            poll_interval = 2.0
        
        socketio.sleep(poll_interval)
        poll_count += 1
        
        try:
            poll_response = requests.get(job_status_url, headers=headers, timeout=10)
            poll_json = poll_response.json()
            status = poll_json.get('status')
            elapsed = time.time() - start_time
            
            if status != last_status:
                print(f"  Poll #{poll_count} ({elapsed:.1f}s): {status}")
                last_status = status

            if status == 'IN_QUEUE':
                socketio.emit('status', {'msg': '⏳ Job queued...'}, to=sid)
                socketio.emit('progress', {'percent': 10}, to=sid)
            
            elif status == 'IN_PROGRESS':
                socketio.emit('status', {'msg': '⚙️ Generating on RunPod...'}, to=sid)
                progress = min(15 + (elapsed * 2), 90)
                socketio.emit('progress', {'percent': progress}, to=sid)

            elif status == 'COMPLETED':
                total_time = time.time() - submit_start
                print(f"✅ RunPod job completed in {total_time:.1f}s!")
                socketio.emit('status', {'msg': '✅ Generation complete!'}, to=sid)
                socketio.emit('progress', {'percent': 100}, to=sid)
                
                output = poll_json.get('output', {})
                
                if output.get('status') == 'success':
                    output['total_time'] = total_time
                    output['poll_count'] = poll_count
                    output['provider'] = 'runpod'
                    socketio.emit('final_sequence', output, to=sid)
                else:
                    error_msg = output.get('message', 'Unknown GPU error')
                    print(f"❌ Job completed but failed: {error_msg}")
                    socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'}, to=sid)

                break

            elif status == 'FAILED':
                print(f"❌ RunPod job failed: {poll_json}")
                error_msg = poll_json.get('output', {}).get('message', 'Unknown GPU error')
                socketio.emit('status', {'msg': f'❌ GPU Error: {error_msg}'}, to=sid)
                break
            
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
    print("🎨 String Art Frontend with GPU Router")
    print("="*60)
    print(f"🌐 Server starting on port {port}")
    
    if HOME_GPU_URL:
        print(f"🏠 Home GPU: {HOME_GPU_URL}")
        if gpu_router.check_home_gpu_health():
            print(f"   ✅ Home GPU is available!")
        else:
            print(f"   ⚠️  Home GPU not responding")
    else:
        print(f"🏠 Home GPU: Disabled")
    
    print(f"☁️  RunPod: Configured as fallback")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)