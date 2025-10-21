# app.py - Simple Flask server for String Art Generator
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/test')
def test():
    """Test route to make sure Flask is working"""
    return "Flask is working! ✅"

if __name__ == '__main__':
    port = 8080
    print(f"\n{'='*60}")
    print(f"🎨 String Art Server")
    print(f"{'='*60}")
    print(f"🌐 Server: http://localhost:{port}")
    print(f"{'='*60}\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)