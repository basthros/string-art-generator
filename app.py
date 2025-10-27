# app.py - Frontend with GPU Router (Home GPU + RunPod Failover)
import eventlet
eventlet.monkey_patch()

import os
import time
import math
from io import BytesIO
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO
import requests

# PDF generation imports
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.lib import colors

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

# DEBUG: Print configuration (this WILL show in gunicorn logs)
print(f"DEBUG: HOME_GPU_URL = {HOME_GPU_URL}")
print(f"DEBUG: GPU Router initialized")
if HOME_GPU_URL:
    health = gpu_router.check_home_gpu_health()
    print(f"DEBUG: Home GPU health check result = {health}")
else:
    print(f"DEBUG: HOME_GPU_URL is not set!")

@app.route('/')
def index():
    """Serve the main index.html file."""
    return render_template('index.html')


def generate_printable_template(num_nails, radius_cm):
    """Generate multi-page printable template with assembly guide"""
    
    # Letter paper dimensions
    PAGE_WIDTH = 8.5 * inch
    PAGE_HEIGHT = 11 * inch
    INSTRUCTION_MARGIN = 0.5 * inch  # Only for instruction page
    
    # Convert radius to inches for PDF
    radius_inches = radius_cm / 2.54
    diameter_inches = radius_inches * 2
    
    # Calculate how many pages needed (grid) - using FULL page, no margins
    pages_x = int(math.ceil(diameter_inches / (PAGE_WIDTH / inch)))
    pages_y = int(math.ceil(diameter_inches / (PAGE_HEIGHT / inch)))
    
    # Calculate total grid dimensions and center the circle
    total_width_inches = pages_x * (PAGE_WIDTH / inch)
    total_height_inches = pages_y * (PAGE_HEIGHT / inch)
    circle_center_x = total_width_inches / 2
    circle_center_y = total_height_inches / 2
    
    # Create PDF in memory
    buffer = BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=letter)
    
    # =========================================================================
    # Page 1: Assembly Guide
    # =========================================================================
    c.setFont("Helvetica-Bold", 16)
    c.drawString(INSTRUCTION_MARGIN, PAGE_HEIGHT - INSTRUCTION_MARGIN, "String Art Template - Assembly Guide")
    
    c.setFont("Helvetica", 12)
    y_pos = PAGE_HEIGHT - INSTRUCTION_MARGIN - 30
    c.drawString(INSTRUCTION_MARGIN, y_pos, f"Circle Diameter: {radius_cm * 2:.1f} cm ({diameter_inches:.1f} inches)")
    y_pos -= 20
    c.drawString(INSTRUCTION_MARGIN, y_pos, f"Number of Nails: {num_nails}")
    y_pos -= 20
    c.drawString(INSTRUCTION_MARGIN, y_pos, f"Template Pages: {pages_x} × {pages_y} = {pages_x * pages_y} pages")
    
    y_pos -= 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(INSTRUCTION_MARGIN, y_pos, "Assembly Instructions:")
    
    y_pos -= 25
    c.setFont("Helvetica", 11)
    instructions = [
        "1. Print all pages at 100% scale (DO NOT scale to fit)",
        "2. Arrange pages according to the grid below",
        "3. Tape pages together on the back side",
        "4. Transfer nail positions to your circular board",
        "5. Hammer small nails at each marked position",
        "6. Follow the numbered sequence to create your string art"
    ]
    
    for instruction in instructions:
        c.drawString(INSTRUCTION_MARGIN, y_pos, instruction)
        y_pos -= 18
    
    # Draw page grid reference
    y_pos -= 30
    c.setFont("Helvetica-Bold", 12)
    c.drawString(INSTRUCTION_MARGIN, y_pos, "Page Layout:")
    y_pos -= 25
    
    # First, detect which pages have nails (non-blank pages)
    pages_with_nails = set()
    for nail_idx in range(num_nails):
        angle = (nail_idx / num_nails) * 2 * math.pi
        nail_x = circle_center_x + radius_inches * math.cos(angle)
        nail_y = circle_center_y + radius_inches * math.sin(angle)
        
        # Determine which page this nail is on
        page_x_idx = int(nail_x / (PAGE_WIDTH / inch))
        page_y_idx = int(nail_y / (PAGE_HEIGHT / inch))
        
        # Check bounds
        if 0 <= page_x_idx < pages_x and 0 <= page_y_idx < pages_y:
            pages_with_nails.add((page_x_idx, page_y_idx))
    
    # Draw grid showing actual page proportions (8.5 x 11 inches)
    # Scale it down to fit on the page
    max_grid_width = 5 * inch  # Maximum width for the grid
    max_grid_height = 6 * inch  # Maximum height for the grid
    
    # Calculate scale to fit
    scale_x = max_grid_width / (pages_x * 8.5)
    scale_y = max_grid_height / (pages_y * 11)
    scale = min(scale_x, scale_y)  # Use smaller scale to fit both dimensions
    
    # Calculate cell dimensions with proper aspect ratio
    cell_width = 8.5 * scale
    cell_height = 11 * scale
    
    # Calculate grid starting position
    grid_start_x = INSTRUCTION_MARGIN
    grid_start_y = y_pos - pages_y * cell_height
    
    # Draw the circle on the layout to show how it spans pages
    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.5)
    c.setDash(2, 2)
    # Circle center should be in the center of the total grid
    layout_circle_center_x = grid_start_x + (pages_x * cell_width) / 2
    layout_circle_center_y = grid_start_y + (pages_y * cell_height) / 2
    layout_circle_radius = radius_inches * scale
    c.circle(layout_circle_center_x, layout_circle_center_y, layout_circle_radius, stroke=1, fill=0)
    c.setDash()  # Reset dash
    
    # Draw page grid - numbering only non-blank pages
    c.setFont("Helvetica", 8)
    pdf_page_num = 2  # Start at P2 (P1 is the guide)
    for reading_row in range(pages_y):
        for px in range(pages_x):
            # Convert reading position to grid coordinates
            py = pages_y - 1 - reading_row
            
            x = grid_start_x + px * cell_width
            # Draw reading_row=0 at TOP of grid (highest y value)
            y = grid_start_y + (pages_y - 1 - reading_row) * cell_height
            
            # Check if this page is blank
            is_blank = (px, py) not in pages_with_nails
            
            if is_blank:
                # Grey out blank pages
                c.setFillColor(colors.lightgrey)
                c.rect(x, y, cell_width, cell_height, stroke=0, fill=1)
                c.setStrokeColor(colors.grey)
                c.setLineWidth(1)
                c.rect(x, y, cell_width, cell_height, stroke=1, fill=0)
                
                # Write "blank" in center
                c.setFillColor(colors.grey)
                c.setFont("Helvetica", 6)
                text = "blank"
                text_width = c.stringWidth(text, "Helvetica", 6)
                c.drawString(x + (cell_width - text_width) / 2, y + cell_height / 2 - 2, text)
            else:
                # Draw normal page box
                c.setStrokeColor(colors.black)
                c.setLineWidth(1)
                c.rect(x, y, cell_width, cell_height, stroke=1, fill=0)
                
                # Center the page number (actual PDF page number)
                c.setFillColor(colors.black)
                c.setFont("Helvetica", 8)
                text = f"P{pdf_page_num}"
                text_width = c.stringWidth(text, "Helvetica", 8)
                c.drawString(x + (cell_width - text_width) / 2, y + cell_height / 2 - 2, text)
                
                # Increment page number only for non-blank pages
                pdf_page_num += 1
    
    c.showPage()  # End assembly guide page
    
    # =========================================================================
    # Generate template pages with nail positions
    # =========================================================================
    # Generate pages in READING ORDER (top to bottom, left to right)
    pdf_page_num = 2  # Start at P2 (P1 is the guide)
    for reading_row in range(pages_y):
        for page_x in range(pages_x):
            # Convert reading position to grid coordinates
            # reading_row=0 is top row, which is page_y=pages_y-1 in PDF coordinates
            page_y = pages_y - 1 - reading_row
            
            # Skip blank pages (pages with no nails)
            if (page_x, page_y) not in pages_with_nails:
                continue
            
            # Use the actual PDF page number
            page_num = pdf_page_num
            pdf_page_num += 1  # Increment for next non-blank page
            
            # Calculate this page's portion of the total grid (in inches)
            # No margins - use full page!
            page_left = page_x * (PAGE_WIDTH / inch)
            page_bottom = page_y * (PAGE_HEIGHT / inch)
            page_right = page_left + (PAGE_WIDTH / inch)
            page_top = page_bottom + (PAGE_HEIGHT / inch)
            
            # Transform to page coordinates (no margin offset!)
            offset_x = -page_left
            offset_y = -page_bottom
            
            # Draw circle outline (it will be clipped by page boundaries)
            c.setStrokeColor(colors.black)
            c.setLineWidth(1)
            
            # Calculate circle center position on this page
            center_x_on_page = (circle_center_x + offset_x) * inch
            center_y_on_page = (circle_center_y + offset_y) * inch
            
            c.circle(center_x_on_page, center_y_on_page, radius_inches * inch, stroke=1, fill=0)
            
            # Add page number in corner for reference
            c.setFont("Helvetica", 10)
            c.setFillColor(colors.grey)
            c.drawString(10, PAGE_HEIGHT - 20, f"P{page_num}")
            c.setFillColor(colors.black)
            
            # Draw nails that fall on this page
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 7)  # Smaller font for less overlap
            
            nails_on_page = 0
            for nail_idx in range(num_nails):
                # Calculate angle - matches tab sequence (0-indexed becomes 1-indexed for display)
                angle = (nail_idx / num_nails) * 2 * math.pi
                nail_x = circle_center_x + radius_inches * math.cos(angle)
                nail_y = circle_center_y + radius_inches * math.sin(angle)
                
                # Check if this nail is on this page (with buffer for numbers)
                margin_buffer = 0.4  # inches - bigger buffer for numbers that bleed off page
                if (page_left - margin_buffer <= nail_x <= page_right + margin_buffer and 
                    page_bottom - margin_buffer <= nail_y <= page_top + margin_buffer):
                    
                    # Convert to page coordinates
                    page_x_pos = (nail_x + offset_x) * inch
                    page_y_pos = (nail_y + offset_y) * inch
                    
                    # Draw nail marker (small circle)
                    c.setLineWidth(1.5)
                    c.circle(page_x_pos, page_y_pos, 3, stroke=1, fill=1)
                    
                    # Draw nail number - position based on angle to avoid overlap
                    nail_num = nail_idx + 1  # 1-indexed to match tab sequence
                    
                    # Calculate text offset based on angle - push numbers outward from center
                    # Much larger offset to prevent overlap especially on vertical sections
                    base_offset = 18  # Increased significantly
                    text_x_offset = base_offset * math.cos(angle)
                    text_y_offset = base_offset * math.sin(angle)
                    
                    # Adjust text position so it doesn't overlap with nail
                    text_x = page_x_pos + text_x_offset
                    text_y = page_y_pos + text_y_offset - 3  # Slight vertical adjustment for centering
                    
                    c.drawString(text_x, text_y, str(nail_num))
                    nails_on_page += 1
            
            c.showPage()  # End this page
    
    # Save PDF
    c.save()
    buffer.seek(0)
    return buffer


@app.route('/download_template/<num_nails>/<radius_cm>')
def download_template(num_nails, radius_cm):
    """Generate and download printable template PDF"""
    try:
        num_nails = int(num_nails)
        radius_cm = float(radius_cm)
        
        print(f"📄 Generating template PDF: {num_nails} nails, {radius_cm}cm radius")
        
        # Generate PDF
        pdf_buffer = generate_printable_template(num_nails, radius_cm)
        
        # Send as downloadable file
        return send_file(
            pdf_buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'string_art_template_{num_nails}nails_{int(radius_cm * 2)}cm.pdf'
        )
    except Exception as e:
        print(f"❌ Error generating template: {e}")
        import traceback
        traceback.print_exc()
        return f"Error generating template: {str(e)}", 500


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
    🚀 OPTIMIZED: Generation with REAL-TIME STREAMING from home GPU
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
        
        # Callback function to handle events from home GPU stream
        def on_stream_event(event_data):
            """Called for each event from home GPU SSE stream"""
            event_type = event_data.get("type")
            
            if event_type == "new_line":
                # 🎨 Real-time line update (single line)
                socketio.emit('new_line', {
                    'start': event_data['start'],
                    'end': event_data['end']
                }, to=sid)
            
            elif event_type == "new_lines_batch":
                # 🎨 Batch of lines (for better network performance)
                for line in event_data.get('lines', []):
                    socketio.emit('new_line', {
                        'start': line['start'],
                        'end': line['end']
                    }, to=sid)
                
            elif event_type == "progress":
                # Progress update
                socketio.emit('progress', {
                    'percent': event_data.get('percent', 0)
                }, to=sid)
                socketio.emit('status', {
                    'msg': f"⚙️ Generating... {event_data['current']}/{event_data['total']} lines"
                }, to=sid)
                
            elif event_type == "error":
                # Error during generation
                socketio.emit('status', {
                    'msg': f"❌ Error: {event_data.get('message', 'Unknown error')}"
                }, to=sid)
        
        # Use GPU router with streaming support
        result, provider = gpu_router.generate_stream(
            image_data=data['imageData'],
            params=data['params'],
            on_event=on_stream_event
        )
        
        # If home GPU was used (with streaming), we're done!
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
        
        # RunPod path - need to poll (same as before)
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

    # Poll RunPod for completion (same as before)
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