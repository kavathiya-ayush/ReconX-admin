import os
import time
import json
import uuid
import base64
import requests as http_requests
from flask import Flask, request, jsonify
import hmac
import hashlib
# Crypto Setup
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from dotenv import load_dotenv
load_dotenv()

PRIVATE_KEY_PEM_DEFAULT = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIAMxsC9FVmSAwtncI9GIKOTpjcftiUMNscesJ4gPfvuf
-----END PRIVATE KEY-----"""

PRIVATE_KEY_PEM = os.environ.get("PRIVATE_KEY_PEM", PRIVATE_KEY_PEM_DEFAULT)
if isinstance(PRIVATE_KEY_PEM, str):
    PRIVATE_KEY_PEM = PRIVATE_KEY_PEM.encode()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hvcysswvpphqobajmkte.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── SUPABASE REST HELPER ────────────────────────────────────────────
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_create_doc(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = http_requests.post(url, headers=sb_headers(), json=data, timeout=10)
    return resp.status_code in [200, 201]

def sb_get_doc(table, doc_id):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}&select=*"
    resp = http_requests.get(url, headers=sb_headers(), timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        if len(data) > 0:
            return data[0]
    return None

def sb_delete_doc(table, doc_id):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}"
    http_requests.delete(url, headers=sb_headers(), timeout=10)

def sb_update_doc(table, doc_id, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}"
    http_requests.patch(url, headers=sb_headers(), json=data, timeout=10)

def sb_query(table, field, op, value):
    # op mapping for Supabase (e.g. eq, gt, lt)
    url = f"{SUPABASE_URL}/rest/v1/{table}?{field}={op}.{value}&select=*"
    resp = http_requests.get(url, headers=sb_headers(), timeout=10)
    if resp.status_code == 200:
        return resp.json()
    return []

# ── FLASK APP ───────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def home():
    return "Server is running."

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_TQ411tgX7goPzl")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

@app.route("/api/create_order", methods=["POST"])
def create_order():
    data = request.json
    amount = data.get("amount", 100) # In INR (rupees)
    
    amount_in_paise = int(amount) * 100
    if amount_in_paise < 100:
        return jsonify({"error": "Amount too low"}), 400

    try:
        resp = http_requests.post(
            "https://api.razorpay.com/v1/orders",
            json={
                "amount": amount_in_paise,
                "currency": "INR",
                "receipt": f"receipt_{uuid.uuid4().hex[:8]}"
            },
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            timeout=10
        )
        if resp.status_code >= 400:
            return jsonify({"error": f"Razorpay API Error: {resp.text}"}), 400
            
        order = resp.json()
        return jsonify({
            "success": True,
            "order_id": order['id'],
            "amount": amount_in_paise,
            "razorpay_key": RAZORPAY_KEY_ID
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/verify_payment", methods=["POST"])
def verify_payment():
    data = request.json
    machine_id = data.get("machine_id")
    nickname = data.get("nickname", "Unknown")
    days = int(data.get("days", 30))
    
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_signature = data.get("razorpay_signature")
    
    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return jsonify({"error": "Missing payment details"}), 400
        
    msg = f"{razorpay_order_id}|{razorpay_payment_id}"
    expected_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode('utf-8'),
        msg.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(expected_signature, razorpay_signature):
        return jsonify({"error": "Signature mismatch"}), 400
        
    # Generate Ed25519 Signed License
    expiry_timestamp = int(time.time()) + (days * 24 * 60 * 60)
    payload = {
        "client": "CA Offline User",
        "machine_id": machine_id,
        "expiry_timestamp": expiry_timestamp,
        "plan": f"{days} Days"
    }
    payload_str = json.dumps(payload)
    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM, password=None)
    signature = private_key.sign(payload_str.encode('utf-8'))
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    try:
        sb_create_doc("active_licenses", {
            "machine_id": machine_id,
            "nickname": nickname,
            "days": days,
            "status": "active"
        })
    except Exception as e:
        print("Supabase insert error:", e)
        
    return jsonify({
        "success": True,
        "payload": payload_str,
        "signature": signature_b64
    })

@app.route("/api/check_revocation", methods=["POST"])
def check_revocation():
    data = request.json
    machine_id = data.get("machine_id")
    
    if not machine_id:
        return jsonify({"revoked": False})
        
    docs = sb_query("active_licenses", "machine_id", "eq", machine_id)
    # Check if ANY license for this machine is revoked
    is_revoked = any(d.get("status") == "revoked" for d in docs)
    
    return jsonify({"revoked": is_revoked})

# ── HTML ────────────────────────────────────────────────────────────
HTML_HEAD = """
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Admin Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body { background: #f8fafc; font-family: 'Inter', sans-serif; }
            .glass-panel {
                background: rgba(255, 255, 255, 0.9);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.2);
                box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.07);
            }
        </style>
    </head>
"""

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    pwd = request.args.get("pwd")
    if pwd != ADMIN_PASSWORD:
        return f"""
        <html>
        {HTML_HEAD}
        <body class="min-h-screen flex items-center justify-center p-4">
            <div class="glass-panel w-full max-w-sm rounded-2xl p-8 text-center">
                <h3 class="text-2xl font-bold text-slate-800 mb-6">Admin Login</h3>
                <form class="flex flex-col gap-4">
                    <input type="password" name="pwd" placeholder="Enter Password" class="w-full text-center px-4 py-3 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
                    <button type="submit" class="w-full bg-slate-800 hover:bg-slate-900 text-white font-medium py-3 rounded-lg transition-colors">Login</button>
                </form>
            </div>
        </body>
        </html>
        """

    active_html = ""
    try:
        docs = sb_query("active_licenses", "status", "eq", "active")
        for p in docs:
            active_html += f"""
            <div class="bg-white border border-slate-200 rounded-xl p-5 mb-4 shadow-sm text-left">
                <div class="flex justify-between items-start mb-4">
                    <div>
                        <p class="text-sm text-slate-500 mb-1">User / Nickname</p>
                        <p class="font-semibold text-slate-800">{p.get('nickname', 'Unknown')}</p>
                    </div>
                    <div class="text-right">
                        <p class="text-sm text-slate-500 mb-1">Plan</p>
                        <p class="font-bold text-blue-600">{p.get('days')} Days</p>
                    </div>
                </div>
                <div class="mb-4">
                    <p class="text-xs text-slate-400">Machine ID</p>
                    <p class="font-mono text-sm text-slate-600 bg-slate-50 p-2 rounded mt-1 break-all">{p.get('machine_id')}</p>
                </div>
                <div class="flex gap-2 m-0">
                    <form action="/admin/revoke" method="POST" class="flex-1 m-0">
                        <input type="hidden" name="pwd" value="{pwd}">
                        <input type="hidden" name="doc_id" value="{p.get('id')}">
                        <button type="submit" class="w-full bg-red-100 hover:bg-red-200 text-red-700 font-medium py-2 rounded-lg transition-colors flex items-center justify-center gap-1 text-sm border border-red-200">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
                            Revoke License
                        </button>
                    </form>
                </div>
            </div>
            """
    except Exception as e:
        active_html = f'<p class="text-red-500">Error loading data: {e}</p>'
    
    if not active_html:
        active_html = """
        <div class="text-center py-12 text-slate-400">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-12 w-12 mx-auto mb-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" /></svg>
            <p>No active users right now.</p>
        </div>
        """

    return f"""
    <html>
    {HTML_HEAD}
    <body class="min-h-screen p-4 md:p-8 flex justify-center">
        <div class="glass-panel w-full max-w-lg rounded-2xl p-6 md:p-8 h-fit">
            <div class="flex items-center justify-between mb-8 border-b border-slate-200 pb-4">
                <div>
                    <h2 class="text-2xl font-bold text-slate-800">Admin Dashboard</h2>
                    <p class="text-sm text-slate-500">Review and approve offline licenses.</p>
                </div>
                <div class="bg-blue-100 text-blue-800 p-2 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                </div>
            </div>
            
            <div class="flex flex-col">
                <h3 class="text-lg font-bold text-slate-800 mb-4">Active Users</h3>
                {active_html}
            </div>
            
            <div class="mt-8 pt-8 border-t border-slate-200">
                <h3 class="text-lg font-bold text-slate-800 mb-4">Manual Code Generation</h3>
                <form action="/admin/manual_generate" method="POST" class="bg-slate-50 p-5 rounded-xl border border-slate-200 shadow-inner flex flex-col gap-4">
                    <input type="hidden" name="pwd" value="{pwd}">
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Machine ID</label>
                        <input type="text" name="machine_id" required placeholder="Paste Machine ID here" class="w-full font-mono text-sm px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
                    </div>
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Plan Duration</label>
                        <select name="days" class="w-full text-sm px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none bg-white">
                            <option value="30">1 Month (30 Days)</option>
                            <option value="60">2 Months (60 Days)</option>
                            <option value="90">3 Months (90 Days)</option>
                        </select>
                    </div>
                    
                    <button type="submit" class="w-full mt-2 bg-slate-800 hover:bg-slate-900 text-white font-medium py-2 rounded-lg transition-colors flex items-center justify-center gap-2">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 text-yellow-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
                        Generate Code Instantly
                    </button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route("/admin/revoke", methods=["POST"])
def admin_revoke():
    pwd = request.form.get("pwd")
    if pwd != ADMIN_PASSWORD:
        return "Unauthorized", 403

    doc_id = request.form.get("doc_id")

    try:
        # Mark license as revoked
        sb_update_doc("active_licenses", doc_id, {
            "status": "revoked"
        })
    except Exception as e:
        return f"Error: {e}", 500

    # Redirect back to dashboard
    return f"""
    <html>
    <head><meta http-equiv="refresh" content="0; url=/admin?pwd={pwd}" /></head>
    <body>Revoking...</body>
    </html>
    """

@app.route("/admin/manual_generate", methods=["POST"])
def admin_manual_generate():
    pwd = request.form.get("pwd")
    if pwd != ADMIN_PASSWORD:
        return "Unauthorized", 403

    machine_id = request.form.get("machine_id", "").strip()
    days = int(request.form.get("days", 30))

    if not machine_id:
        return "Machine ID is required", 400

    # Generate Short Code
    raw_uuid = str(uuid.uuid4()).upper().replace("-", "")
    short_code = f"{raw_uuid[:4]}-{raw_uuid[4:8]}"

    try:
        # Save activation code directly
        sb_create_doc("activation_codes", {
            "id": short_code,
            "machine_id": machine_id,
            "days": days
        })
    except Exception as e:
        return f"Error: {e}", 500

    return f"""
    <html>
    {HTML_HEAD}
    <body class="min-h-screen p-4 flex items-center justify-center">
        <div class="glass-panel w-full max-w-md rounded-2xl p-8 text-center">
            <div class="mx-auto w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mb-4">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>
            </div>
            <h2 class="text-2xl font-bold text-slate-800 mb-2">Code Generated!</h2>
            <p class="text-sm text-slate-500 mb-6">Send this code to the user for Machine ID: <br><span class="font-mono text-xs">{machine_id}</span></p>
            
            <div class="bg-slate-50 border-2 border-dashed border-slate-300 rounded-xl p-4 md:p-6 mb-8 w-full overflow-hidden">
                <div class="font-mono text-2xl md:text-4xl font-bold text-blue-600 tracking-widest break-all whitespace-nowrap">{short_code}</div>
            </div>
            
            <a href="/admin?pwd={pwd}" class="inline-flex items-center gap-2 text-slate-600 hover:text-slate-900 transition-colors font-medium">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" /></svg>
                Back to Dashboard
            </a>
        </div>
    </body>
    </html>
    """

@app.route("/api/exchange", methods=["POST"])
def exchange():
    data = request.json
    machine_id = data.get("machine_id")
    short_code = data.get("short_code")
    
    try:
        record = sb_get_doc("activation_codes", short_code)
    except Exception as e:
        return jsonify({"error": f"Server error: {e}"}), 500
        
    if not record:
        return jsonify({"error": "Invalid or expired code."}), 400
        
    if record["machine_id"] != machine_id:
        return jsonify({"error": "This code was purchased for a different machine."}), 403
        
    days = record["days"]
    expiry_timestamp = int(time.time()) + (days * 24 * 60 * 60)
    
    payload = {
        "client": "CA Offline User",
        "machine_id": machine_id,
        "expiry_timestamp": expiry_timestamp,
        "plan": f"{days} Days"
    }
    
    payload_str = json.dumps(payload)
    
    private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM, password=None)
    signature = private_key.sign(payload_str.encode('utf-8'))
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    # Delete so code can't be reused
    try:
        sb_delete_doc("activation_codes", short_code)
    except:
        pass
    
    return jsonify({
        "payload": payload_str,
        "signature": signature_b64
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
