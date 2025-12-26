"""
Ring Intercom One-Touch Unlock Server
=====================================
A simple Flask server that provides a single endpoint to unlock your Ring Intercom.
Designed to be called from an iOS Shortcut for one-tap door unlocking.
"""

import os
import json
import asyncio
import base64
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
API_KEY = os.environ.get('API_KEY', '')
RING_USERNAME = os.environ.get('RING_USERNAME', '')
RING_PASSWORD = os.environ.get('RING_PASSWORD', '')
INTERCOM_NAME = os.environ.get('INTERCOM_NAME', '')
RING_TOKEN = os.environ.get('RING_TOKEN', '')  # Base64 encoded token JSON

# Token storage path (use /data for Render's persistent disk, fallback to local)
if os.path.exists('/data'):
    TOKEN_FILE = Path('/data/ring_token.json')
else:
    TOKEN_FILE = Path('ring_token.json')

# User agent for Ring API
USER_AGENT = "RingUnlockServer-1.0"

# Global variable to store the latest token for display
_latest_token_b64 = None


def require_api_key(f):
    """Decorator to require API key for protected endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        if not API_KEY:
            return jsonify({'error': 'Server not configured - API_KEY not set'}), 500
        if provided_key != API_KEY:
            return jsonify({'error': 'Invalid or missing API key'}), 401
        return f(*args, **kwargs)
    return decorated


def token_updated(token):
    """Callback to save updated token."""
    global _latest_token_b64
    
    # Save to file (works if persistent storage available)
    try:
        TOKEN_FILE.write_text(json.dumps(token))
        print(f"Token saved to {TOKEN_FILE}")
    except Exception as e:
        print(f"Could not save token to file: {e}")
    
    # Also encode as base64 for environment variable storage
    token_json = json.dumps(token)
    token_b64 = base64.b64encode(token_json.encode()).decode()
    _latest_token_b64 = token_b64
    
    # Log the token for manual env var update (important for free tier!)
    print(f"\n{'='*60}")
    print("TOKEN UPDATED! Copy this value to your RING_TOKEN env var:")
    print(f"{'='*60}")
    print(token_b64)
    print(f"{'='*60}\n")


def get_cached_token():
    """Load cached token from environment variable or file."""
    global RING_TOKEN
    
    # First, try environment variable (most reliable for Render free tier)
    if RING_TOKEN:
        try:
            token_json = base64.b64decode(RING_TOKEN.encode()).decode()
            return json.loads(token_json)
        except Exception as e:
            print(f"Error decoding RING_TOKEN env var: {e}")
    
    # Fallback to file
    if TOKEN_FILE.is_file():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (json.JSONDecodeError, Exception) as e:
            print(f"Error reading token file: {e}")
    
    return None



async def get_ring_client():
    """Get an authenticated Ring client."""
    from ring_doorbell import Auth, Ring, AuthenticationError
    
    cached_token = get_cached_token()
    
    if cached_token:
        auth = Auth(USER_AGENT, cached_token, token_updated)
        ring = Ring(auth)
        try:
            await ring.async_create_session()
            await ring.async_update_data()
            return ring, auth
        except AuthenticationError:
            print("Cached token expired, need re-authentication")
            return None, None
    
    return None, None


async def find_intercom(ring):
    """Find the Ring Intercom device."""
    devices = ring.devices()
    
    # RingDevices has attributes like: doorbots, chimes, stickup_cams, other
    # Intercoms are typically in 'other' category
    all_devices = []
    
    # Collect all devices from the RingDevices object
    if hasattr(devices, 'other'):
        all_devices.extend(devices.other)
    if hasattr(devices, 'doorbots'):
        all_devices.extend(devices.doorbots)
    if hasattr(devices, 'stickup_cams'):
        all_devices.extend(devices.stickup_cams)
    if hasattr(devices, 'chimes'):
        all_devices.extend(devices.chimes)
    
    # Also try the video_doorbells and all_devices attributes
    if hasattr(devices, 'video_doorbells'):
        all_devices.extend(devices.video_doorbells)
        
    # Try devices_combined if available
    if hasattr(devices, 'devices_combined'):
        all_devices = list(devices.devices_combined)
    
    # If INTERCOM_NAME is set, find that specific device by name
    if INTERCOM_NAME:
        for device in all_devices:
            if hasattr(device, 'name') and device.name.lower() == INTERCOM_NAME.lower():
                return device
    
    # Otherwise, look for devices that could be intercoms
    # Ring Intercoms are in 'other' category, so check for:
    # 1. Devices with 'intercom' in type/family/name
    # 2. Devices in 'other' family (likely intercoms)
    intercom_devices = []
    other_devices = []
    
    for device in all_devices:
        device_type = str(type(device)).lower()
        device_family = getattr(device, 'family', '').lower() if hasattr(device, 'family') else ''
        device_name = getattr(device, 'name', '').lower() if hasattr(device, 'name') else ''
        
        # Explicit intercom detection
        if 'intercom' in device_type or 'intercom' in device_family or 'intercom' in device_name:
            intercom_devices.append(device)
        # Ring Intercoms are categorized as 'other'
        elif device_family == 'other':
            other_devices.append(device)
    
    # Prefer explicit intercoms, fallback to 'other' devices
    if intercom_devices:
        return intercom_devices[0]
    elif other_devices:
        return other_devices[0]
    
    return None


async def unlock_door_async():
    """Attempt to unlock the door via Ring Intercom."""
    ring, auth = await get_ring_client()
    
    if not ring:
        return False, "Not authenticated. Please visit /setup to authenticate."
    
    try:
        intercom = await find_intercom(ring)
        
        if not intercom:
            # List all devices for debugging
            devices = ring.devices()
            device_list = []
            
            # Collect device info for debugging
            all_devices = getattr(devices, 'devices_combined', [])
            if not all_devices and hasattr(devices, 'other'):
                all_devices = devices.other
            
            for d in all_devices:
                name = getattr(d, 'name', 'Unknown')
                family = getattr(d, 'family', 'Unknown')
                device_list.append(f"{name} ({family})")
            
            return False, f"No intercom found. Available devices: {device_list}"
        
        # Unlock the door
        await intercom.async_open_door()
        return True, f"Door unlocked via {intercom.name}!"
    
    except Exception as e:
        return False, f"Error unlocking door: {str(e)}"
    finally:
        if auth:
            await auth.async_close()


def run_async(coro):
    """Helper to run async code from sync Flask handlers."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def home():
    """Home page with status."""
    authenticated = get_cached_token() is not None
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ring Unlock Server</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
            }
            .card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }
            h1 { margin-top: 0; }
            .status {
                display: inline-block;
                padding: 8px 16px;
                border-radius: 20px;
                font-weight: 600;
            }
            .status.ok { background: #00c853; color: #000; }
            .status.warning { background: #ff9800; color: #000; }
            a {
                color: #64b5f6;
                text-decoration: none;
            }
            a:hover { text-decoration: underline; }
            .endpoint {
                background: rgba(0,0,0,0.3);
                padding: 12px;
                border-radius: 8px;
                margin: 10px 0;
                font-family: monospace;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔔 Ring Unlock Server</h1>
            <p>Status: 
                {% if authenticated %}
                <span class="status ok">✓ Authenticated</span>
                {% else %}
                <span class="status warning">⚠ Not Authenticated</span>
                {% endif %}
            </p>
            {% if not authenticated %}
            <p><a href="/setup">→ Complete Setup</a></p>
            {% endif %}
        </div>
        
        <div class="card">
            <h2>📱 iOS Shortcut Setup</h2>
            <p>Create a shortcut with these settings:</p>
            <div class="endpoint">
                <strong>URL:</strong> {{ request.url_root }}unlock<br>
                <strong>Method:</strong> POST<br>
                <strong>Headers:</strong> X-API-Key: [your-api-key]
            </div>
        </div>
        
        <div class="card">
            <h2>🔗 Endpoints</h2>
            <p><code>/unlock</code> - Unlock the door (requires API key)</p>
            <p><code>/health</code> - Health check</p>
            <p><code>/setup</code> - Authentication setup</p>
        </div>
    </body>
    </html>
    ''', authenticated=authenticated)


@app.route('/health')
def health():
    """Health check endpoint for Render."""
    authenticated = get_cached_token() is not None
    return jsonify({
        'status': 'healthy',
        'authenticated': authenticated
    })


@app.route('/get-token')
@require_api_key
def get_token():
    """Get the current token as base64 for environment variable storage."""
    token = get_cached_token()
    if not token:
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>No Token - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 500px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                }
                a { color: #64b5f6; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>❌ No Token Found</h1>
                <p>No authentication token is stored. Please authenticate first.</p>
                <p><a href="/setup">→ Go to Setup</a></p>
            </div>
        </body>
        </html>
        ''')
    
    # Encode token as base64
    token_json = json.dumps(token)
    token_b64 = base64.b64encode(token_json.encode()).decode()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Ring Token - Ring Unlock Server</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
            }
            .card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                padding: 24px;
                border: 1px solid rgba(255,255,255,0.1);
            }
            .token-box {
                background: rgba(0,0,0,0.4);
                padding: 12px;
                border-radius: 8px;
                word-break: break-all;
                font-family: monospace;
                font-size: 11px;
                margin: 12px 0;
                max-height: 150px;
                overflow-y: auto;
            }
            button {
                background: #00c853;
                color: #000;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                cursor: pointer;
                font-weight: 600;
                font-size: 16px;
            }
            button:hover { background: #00e676; }
            a { color: #64b5f6; }
            .info {
                background: rgba(100,181,246,0.2);
                border: 1px solid #64b5f6;
                padding: 12px;
                border-radius: 8px;
                margin-bottom: 16px;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔑 Your Ring Token</h1>
            <div class="info">
                Copy this value and add it as <strong>RING_TOKEN</strong> environment variable in Render.
            </div>
            <div class="token-box" id="token">{{ token_b64 }}</div>
            <button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText); this.innerText='✓ Copied!';">Copy Token</button>
            <p style="margin-top: 20px;"><a href="/">← Back to Home</a></p>
        </div>
    </body>
    </html>
    ''', token_b64=token_b64)


@app.route('/unlock', methods=['GET', 'POST'])
@require_api_key
def unlock():
    """Unlock the door - the main endpoint for iOS Shortcuts."""
    success, message = run_async(unlock_door_async())
    
    if success:
        return jsonify({
            'success': True,
            'message': message
        })
    else:
        return jsonify({
            'success': False,
            'error': message
        }), 400


@app.route('/setup')
def setup_page():
    """Setup page for Ring authentication."""
    authenticated = get_cached_token() is not None
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Setup - Ring Unlock Server</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { box-sizing: border-box; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 500px;
                margin: 0 auto;
                padding: 20px;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                color: #fff;
            }
            .card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 16px;
                padding: 24px;
                margin-bottom: 20px;
                border: 1px solid rgba(255,255,255,0.1);
            }
            h1 { margin-top: 0; }
            .form-group { margin-bottom: 16px; }
            label {
                display: block;
                margin-bottom: 6px;
                font-weight: 500;
            }
            input {
                width: 100%;
                padding: 12px;
                border-radius: 8px;
                border: 1px solid rgba(255,255,255,0.2);
                background: rgba(0,0,0,0.3);
                color: #fff;
                font-size: 16px;
            }
            input::placeholder { color: rgba(255,255,255,0.5); }
            button {
                width: 100%;
                padding: 14px;
                border-radius: 8px;
                border: none;
                background: #00c853;
                color: #000;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
            }
            button:hover { background: #00e676; }
            .success {
                background: rgba(0,200,83,0.2);
                border: 1px solid #00c853;
                padding: 16px;
                border-radius: 8px;
                margin-bottom: 16px;
            }
            .error {
                background: rgba(255,0,0,0.2);
                border: 1px solid #ff5252;
                padding: 16px;
                border-radius: 8px;
                margin-bottom: 16px;
            }
            a { color: #64b5f6; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🔐 Ring Authentication</h1>
            
            {% if authenticated %}
            <div class="success">
                ✓ Already authenticated! Your Ring account is connected.
            </div>
            <p><a href="/">← Back to Home</a></p>
            {% else %}
            <p>Enter your Ring credentials to connect your account. This is a one-time setup.</p>
            
            <form action="/setup/authenticate" method="POST">
                <div class="form-group">
                    <label for="username">Ring Email</label>
                    <input type="email" id="username" name="username" 
                           value="{{ ring_username }}" placeholder="your@email.com" required>
                </div>
                <div class="form-group">
                    <label for="password">Ring Password</label>
                    <input type="password" id="password" name="password" 
                           placeholder="Your Ring password" required>
                </div>
                <button type="submit">Connect to Ring →</button>
            </form>
            {% endif %}
        </div>
    </body>
    </html>
    ''', authenticated=authenticated, ring_username=RING_USERNAME)


@app.route('/setup/authenticate', methods=['POST'])
def setup_authenticate():
    """Handle initial authentication (will trigger 2FA)."""
    from ring_doorbell import Auth, Requires2FAError
    
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    
    async def do_auth():
        auth = Auth(USER_AGENT, None, token_updated)
        try:
            await auth.async_fetch_token(username, password)
            return 'success', None
        except Requires2FAError:
            return '2fa_required', auth
        except Exception as e:
            return 'error', str(e)
    
    result, data = run_async(do_auth())
    
    if result == 'success':
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Success - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 500px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                    text-align: center;
                }
                .success-icon { font-size: 64px; margin-bottom: 16px; }
                a { color: #64b5f6; }
            </style>
        </head>
        <body>
            <div class="card">
                <div class="success-icon">✅</div>
                <h1>Connected!</h1>
                <p>Your Ring account is now connected. You can now use the unlock endpoint.</p>
                <p><a href="/">← Back to Home</a></p>
            </div>
        </body>
        </html>
        ''')
    
    elif result == '2fa_required':
        # Store credentials in session for 2FA verification
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>2FA Required - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * { box-sizing: border-box; }
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 500px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                }
                h1 { margin-top: 0; }
                .form-group { margin-bottom: 16px; }
                label { display: block; margin-bottom: 6px; font-weight: 500; }
                input {
                    width: 100%;
                    padding: 12px;
                    border-radius: 8px;
                    border: 1px solid rgba(255,255,255,0.2);
                    background: rgba(0,0,0,0.3);
                    color: #fff;
                    font-size: 24px;
                    text-align: center;
                    letter-spacing: 8px;
                }
                button {
                    width: 100%;
                    padding: 14px;
                    border-radius: 8px;
                    border: none;
                    background: #00c853;
                    color: #000;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                }
                button:hover { background: #00e676; }
                .info {
                    background: rgba(100,181,246,0.2);
                    border: 1px solid #64b5f6;
                    padding: 12px;
                    border-radius: 8px;
                    margin-bottom: 16px;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>📱 Enter 2FA Code</h1>
                <div class="info">
                    Ring has sent a verification code to your phone or email.
                </div>
                <form action="/setup/verify-2fa" method="POST">
                    <input type="hidden" name="username" value="{{ username }}">
                    <input type="hidden" name="password" value="{{ password }}">
                    <div class="form-group">
                        <label for="code">Verification Code</label>
                        <input type="text" id="code" name="code" 
                               maxlength="6" pattern="[0-9]{6}" 
                               placeholder="000000" required autofocus>
                    </div>
                    <button type="submit">Verify →</button>
                </form>
            </div>
        </body>
        </html>
        ''', username=username, password=password)
    
    else:
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 500px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                }
                .error {
                    background: rgba(255,0,0,0.2);
                    border: 1px solid #ff5252;
                    padding: 16px;
                    border-radius: 8px;
                }
                a { color: #64b5f6; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>❌ Authentication Failed</h1>
                <div class="error">{{ error }}</div>
                <p><a href="/setup">← Try Again</a></p>
            </div>
        </body>
        </html>
        ''', error=data)


@app.route('/setup/verify-2fa', methods=['POST'])
def setup_verify_2fa():
    """Handle 2FA verification."""
    from ring_doorbell import Auth, Ring
    
    username = request.form.get('username', '')
    password = request.form.get('password', '')
    code = request.form.get('code', '')
    
    async def verify_2fa():
        auth = Auth(USER_AGENT, None, token_updated)
        try:
            await auth.async_fetch_token(username, password, code)
            # Verify it works by creating a session
            ring = Ring(auth)
            await ring.async_create_session()
            await ring.async_update_data()
            await auth.async_close()
            return True, None
        except Exception as e:
            return False, str(e)
    
    success, error = run_async(verify_2fa())
    
    if success:
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Success - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                    text-align: center;
                    margin-bottom: 20px;
                }
                .success-icon { font-size: 64px; margin-bottom: 16px; }
                a { color: #64b5f6; }
                .warning {
                    background: rgba(255,152,0,0.2);
                    border: 1px solid #ff9800;
                    padding: 16px;
                    border-radius: 8px;
                    text-align: left;
                    margin-top: 16px;
                }
                .token-box {
                    background: rgba(0,0,0,0.4);
                    padding: 12px;
                    border-radius: 8px;
                    word-break: break-all;
                    font-family: monospace;
                    font-size: 11px;
                    margin: 12px 0;
                    text-align: left;
                    max-height: 100px;
                    overflow-y: auto;
                }
                button {
                    background: #00c853;
                    color: #000;
                    border: none;
                    padding: 10px 20px;
                    border-radius: 8px;
                    cursor: pointer;
                    font-weight: 600;
                }
            </style>
        </head>
        <body>
            <div class="card">
                <div class="success-icon">🎉</div>
                <h1>All Set!</h1>
                <p>Your Ring account is connected and ready to use!</p>
                
                {% if token_b64 %}
                <div class="warning">
                    <strong>⚠️ Important for Render Free Tier:</strong>
                    <p>To keep authentication working after server restarts, add this as an environment variable in Render:</p>
                    <p><strong>Name:</strong> <code>RING_TOKEN</code></p>
                    <p><strong>Value:</strong></p>
                    <div class="token-box" id="token">{{ token_b64 }}</div>
                    <button onclick="navigator.clipboard.writeText(document.getElementById('token').innerText); this.innerText='Copied!';">Copy Token</button>
                </div>
                {% endif %}
                
                <p style="margin-top: 20px;"><a href="/">← Back to Home</a></p>
            </div>
        </body>
        </html>
        ''', token_b64=_latest_token_b64)
    else:
        return render_template_string('''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Error - Ring Unlock Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    max-width: 500px;
                    margin: 0 auto;
                    padding: 20px;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    min-height: 100vh;
                    color: #fff;
                }
                .card {
                    background: rgba(255,255,255,0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 16px;
                    padding: 24px;
                    border: 1px solid rgba(255,255,255,0.1);
                }
                .error {
                    background: rgba(255,0,0,0.2);
                    border: 1px solid #ff5252;
                    padding: 16px;
                    border-radius: 8px;
                }
                a { color: #64b5f6; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>❌ Verification Failed</h1>
                <div class="error">{{ error }}</div>
                <p><a href="/setup">← Try Again</a></p>
            </div>
        </body>
        </html>
        ''', error=error)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
