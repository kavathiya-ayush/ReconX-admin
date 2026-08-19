import os
import time
import json
import uuid
import base64
from datetime import datetime
import requests as http_requests
from flask import Flask, request, jsonify
import hmac
import hashlib
# Crypto Setup
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

try:
    from dotenv import load_dotenv
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        load_dotenv(env_file)
    else:
        load_dotenv()
except Exception:
    pass

PRIVATE_KEY_PEM_DEFAULT = b"""-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIAMxsC9FVmSAwtncI9GIKOTpjcftiUMNscesJ4gPfvuf
-----END PRIVATE KEY-----"""

PRIVATE_KEY_PEM = os.environ.get("PRIVATE_KEY_PEM", PRIVATE_KEY_PEM_DEFAULT)
if isinstance(PRIVATE_KEY_PEM, str):
    PRIVATE_KEY_PEM = PRIVATE_KEY_PEM.encode()

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")

DEFAULT_SB_KEY = base64.b64decode("c2Jfc2VjcmV0XzB5S0d0cmJxcTM3Mk5feDRHR3EzN0FfQXM5NmVDNVo=").decode('utf-8')
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hvcysswvpphqobajmkte.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or DEFAULT_SB_KEY

# ── SUPABASE REST HELPER ────────────────────────────────────────────
def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_create_doc(table, data):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        resp = http_requests.post(url, headers=sb_headers(), json=data, timeout=8)
        return resp.status_code in [200, 201]
    except Exception as e:
        print(f"sb_create_doc error: {e}")
        return False

def sb_get_doc(table, doc_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}&select=*"
        resp = http_requests.get(url, headers=sb_headers(), timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if len(data) > 0:
                return data[0]
    except Exception as e:
        print(f"sb_get_doc error: {e}")
    return None

def sb_delete_doc(table, doc_id):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}"
        http_requests.delete(url, headers=sb_headers(), timeout=8)
    except Exception as e:
        print(f"sb_delete_doc error: {e}")

def sb_update_doc(table, doc_id, data):
    try:
        url = f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{doc_id}"
        http_requests.patch(url, headers=sb_headers(), json=data, timeout=8)
    except Exception as e:
        print(f"sb_update_doc error: {e}")

def sb_query(table, field=None, op=None, value=None):
    try:
        if field and op and value:
            url = f"{SUPABASE_URL}/rest/v1/{table}?{field}={op}.{value}&select=*"
        else:
            url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
        resp = http_requests.get(url, headers=sb_headers(), timeout=8)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"sb_query error: {e}")
    return []

# ── FLASK APP ───────────────────────────────────────────────────────
app = Flask(__name__)

@app.route("/")
def home():
    return "Server is running."

@app.route("/api/latest-version", methods=["GET"])
@app.route("/api/latest_version", methods=["GET"])
def get_latest_version():
    version = "1.7.5"
    try:
        resp = http_requests.get("https://raw.githubusercontent.com/kavathiya-ayush/CA-Converter-Releases/main/version.json", timeout=5)
        if resp.status_code == 200:
            version_data = resp.json()
            version = version_data.get("version", "1.7.5")
    except Exception:
        pass

    return jsonify({
        "version": version,
        "url": f"https://raw.githubusercontent.com/kavathiya-ayush/CA-Converter-Releases/main/CA_Bank_Converter.exe?t={int(time.time())}",
        "download_url": f"https://raw.githubusercontent.com/kavathiya-ayush/CA-Converter-Releases/main/CA_Bank_Converter.exe?t={int(time.time())}",
        "release_notes": "Added SBI WhatsApp Banking, ICICI Web Portal, and Central Bank of India support."
    })

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_TR6dzZ6s5mNkvW")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "j8tqtPAD1niv7C7EovUHBJrh")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "ReconX_Secret_Webhook_2026")

@app.route("/api/create_order", methods=["POST"])
def create_order():
    data = request.json or {}
    amount = data.get("amount", 599) # In INR (rupees)
    machine_id = data.get("machine_id", "UNKNOWN")
    days = int(data.get("days", 60))
    
    amount_in_paise = int(amount) * 100
    if amount_in_paise < 100:
        return jsonify({"error": "Amount too low"}), 400

    try:
        resp = http_requests.post(
            "https://api.razorpay.com/v1/orders",
            json={
                "amount": amount_in_paise,
                "currency": "INR",
                "receipt": f"rx_{uuid.uuid4().hex[:8]}",
                "notes": {
                    "machine_id": machine_id,
                    "days": str(days)
                }
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
            "currency": "INR",
            "razorpay_key": RAZORPAY_KEY_ID
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/verify_payment", methods=["POST"])
def verify_payment():
    data = request.json or {}
    machine_id = data.get("machine_id")
    nickname = data.get("nickname", "User")
    days = int(data.get("days", 60))
    
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
        "client": "ReconX Pro User",
        "machine_id": machine_id,
        "expiry_timestamp": expiry_timestamp,
        "plan": f"{days} Days",
        "order_id": razorpay_order_id,
        "payment_id": razorpay_payment_id
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
            "status": "active",
            "order_id": razorpay_order_id,
            "payment_id": razorpay_payment_id
        })
    except Exception as e:
        print("Supabase insert error:", e)
        
    return jsonify({
        "success": True,
        "payload": payload_str,
        "signature": signature_b64
    })

@app.route("/api/check_order_status", methods=["GET"])
def check_order_status():
    order_id = request.args.get("order_id")
    machine_id = request.args.get("machine_id")
    days = int(request.args.get("days", 60))
    
    if not order_id:
        return jsonify({"paid": False, "error": "Order ID required"}), 400

    try:
        resp = http_requests.get(
            f"https://api.razorpay.com/v1/orders/{order_id}",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            timeout=10
        )
        if resp.status_code == 200:
            order = resp.json()
            if order.get("status") == "paid":
                # Generate Ed25519 Signed License
                expiry_timestamp = int(time.time()) + (days * 24 * 60 * 60)
                payload = {
                    "client": "ReconX Pro User",
                    "machine_id": machine_id,
                    "expiry_timestamp": expiry_timestamp,
                    "plan": f"{days} Days",
                    "order_id": order_id
                }
                payload_str = json.dumps(payload)
                private_key = serialization.load_pem_private_key(PRIVATE_KEY_PEM, password=None)
                signature = private_key.sign(payload_str.encode('utf-8'))
                signature_b64 = base64.b64encode(signature).decode('utf-8')

                return jsonify({
                    "paid": True,
                    "payload": payload_str,
                    "signature": signature_b64,
                    "order_id": order_id
                })
        return jsonify({"paid": False})
    except Exception as e:
        return jsonify({"paid": False, "error": str(e)})

@app.route("/api/razorpay_webhook", methods=["POST"])
def razorpay_webhook():
    webhook_signature = request.headers.get("X-Razorpay-Signature", "")
    webhook_body = request.data.decode("utf-8")
    
    if RAZORPAY_WEBHOOK_SECRET:
        expected_sig = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
            request.data,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_sig, webhook_signature):
            return jsonify({"status": "invalid_signature"}), 400

    try:
        event_data = request.json or {}
        event = event_data.get("event")
        payload = event_data.get("payload", {})
        payment_entity = payload.get("payment", {}).get("entity", {})
        order_entity = payload.get("order", {}).get("entity", {})
        
        notes = payment_entity.get("notes") or order_entity.get("notes") or {}
        machine_id = notes.get("machine_id")
        days = int(notes.get("days", 60))
        
        if event in ["payment.captured", "order.paid"] and machine_id:
            try:
                sb_create_doc("active_licenses", {
                    "machine_id": machine_id,
                    "nickname": "UPI / QR User",
                    "days": days,
                    "status": "active",
                    "payment_id": payment_entity.get("id"),
                    "order_id": order_entity.get("id") or payment_entity.get("order_id")
                })
            except Exception as e:
                print("Supabase webhook insert error:", e)

        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/register_active_license", methods=["POST"])
def register_active_license():
    data = request.json or {}
    machine_id = data.get("machine_id")
    nickname = data.get("nickname", "User")
    days = int(data.get("days", 60))
    order_id = data.get("order_id", f"rx_{uuid.uuid4().hex[:8]}")
    payment_id = data.get("payment_id", f"pay_{uuid.uuid4().hex[:8]}")
    
    if not machine_id:
        return jsonify({"error": "Machine ID is required"}), 400
        
    now = int(time.time())
    expires_at = now + (days * 24 * 60 * 60)
    
    try:
        # Check if license already recorded for this machine
        existing = sb_query("active_licenses", "machine_id", "eq", machine_id)
        if existing and len(existing) > 0:
            doc_id = existing[0].get("id")
            sb_update_doc("active_licenses", doc_id, {
                "nickname": nickname,
                "days": days,
                "status": "active",
                "order_id": order_id,
                "payment_id": payment_id,
                "created_at": now,
                "expires_at": expires_at
            })
        else:
            sb_create_doc("active_licenses", {
                "machine_id": machine_id,
                "nickname": nickname,
                "days": days,
                "status": "active",
                "order_id": order_id,
                "payment_id": payment_id,
                "created_at": now,
                "expires_at": expires_at
            })
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        <title>ReconX Admin Dashboard</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            body { background: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
            .glass-panel {
                background: rgba(30, 41, 59, 0.7);
                backdrop-filter: blur(16px);
                border: 1px solid rgba(255, 255, 255, 0.08);
                box-shadow: 0 20px 40px 0 rgba(0, 0, 0, 0.3);
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
            <div class="glass-panel w-full max-w-sm rounded-3xl p-8 text-center text-white">
                <div class="w-12 h-12 bg-red-500/20 text-red-400 rounded-2xl flex items-center justify-center mx-auto mb-4 border border-red-500/30">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg>
                </div>
                <h3 class="text-xl font-bold text-white mb-2">ReconX Admin Portal</h3>
                <p class="text-xs text-slate-400 mb-6">Enter security password to access licenses</p>
                <form class="flex flex-col gap-3">
                    <input type="password" name="pwd" placeholder="Enter Password" class="w-full text-center px-4 py-3 bg-slate-800/80 border border-slate-700 text-white rounded-xl focus:ring-2 focus:ring-red-500 focus:outline-none text-sm">
                    <button type="submit" class="w-full bg-red-600 hover:bg-red-700 text-white font-semibold py-3 rounded-xl transition-all shadow-lg shadow-red-600/30 text-sm">Sign In</button>
                </form>
            </div>
        </body>
        </html>
        """

    now_ts = int(time.time())
    total_active = 0
    expiring_soon = 0
    total_revoked = 0

    try:
        active_docs = sb_query("active_licenses", "status", "eq", "active")
        total_active = len(active_docs)
        for p in active_docs:
            days = int(p.get("days", 30))
            raw_created = p.get("created_at")
            created_ts = now_ts
            if isinstance(raw_created, str):
                try:
                    clean_iso = raw_created.replace('Z', '+00:00')
                    created_ts = int(datetime.fromisoformat(clean_iso).timestamp())
                except Exception:
                    created_ts = now_ts

            raw_expires = p.get("expires_at")
            if isinstance(raw_expires, (int, float)):
                expires_at = int(raw_expires)
            elif isinstance(raw_expires, str):
                try:
                    clean_iso = raw_expires.replace('Z', '+00:00')
                    expires_at = int(datetime.fromisoformat(clean_iso).timestamp())
                except Exception:
                    expires_at = created_ts + (days * 86400)
            else:
                expires_at = created_ts + (days * 86400)

            diff_seconds = max(0, expires_at - now_ts)
            days_left = diff_seconds // 86400
            if days_left <= 7:
                expiring_soon += 1

        revoked_docs = sb_query("active_licenses", "status", "eq", "revoked")
        total_revoked = len(revoked_docs)
    except Exception:
        pass

    return f"""
    <html>
    {HTML_HEAD}
    <body class="min-h-screen p-4 md:p-8 flex justify-center text-white">
        <div class="glass-panel w-full max-w-xl rounded-3xl p-6 md:p-8 h-fit">
            <div class="flex items-center justify-between mb-6 border-b border-slate-700/80 pb-5">
                <div>
                    <h2 class="text-2xl font-black tracking-tight text-white flex items-center gap-2">
                        <span>RECONX</span>
                        <span class="text-xs bg-red-500/20 text-red-400 font-bold px-2.5 py-0.5 rounded-full border border-red-500/30">ADMIN</span>
                    </h2>
                    <p class="text-xs text-slate-400 mt-1">License & payment authorization hub</p>
                </div>
                <div class="flex items-center gap-2">
                    <a href="/admin?pwd={pwd}" class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors border border-slate-700 text-xs flex items-center gap-1.5">
                        🔄 Refresh
                    </a>
                </div>
            </div>

            <!-- Stats Grid -->
            <div class="grid grid-cols-3 gap-3 mb-6">
                <div class="bg-slate-800/80 border border-slate-700/80 p-4 rounded-2xl text-center">
                    <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Active</p>
                    <p class="text-2xl font-black text-emerald-400">{total_active}</p>
                </div>
                <div class="bg-slate-800/80 border border-slate-700/80 p-4 rounded-2xl text-center">
                    <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Expiring</p>
                    <p class="text-2xl font-black text-amber-400">{expiring_soon}</p>
                </div>
                <div class="bg-slate-800/80 border border-slate-700/80 p-4 rounded-2xl text-center">
                    <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mb-1">Revoked</p>
                    <p class="text-2xl font-black text-red-400">{total_revoked}</p>
                </div>
            </div>

            <!-- Full Screen View Button -->
            <div class="mb-8">
                <a href="/admin/users?pwd={pwd}" class="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold py-4 px-6 rounded-2xl transition-all shadow-xl shadow-blue-500/20 flex items-center justify-between group">
                    <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-xl bg-white/20 flex items-center justify-center text-lg">
                            👥
                        </div>
                        <div class="text-left">
                            <h4 class="font-bold text-sm text-white">View All Active Users</h4>
                            <p class="text-xs text-blue-100/70">Full-screen user directory & license manager</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="px-2.5 py-1 bg-white/20 rounded-full text-xs font-mono font-bold text-white">{total_active} Users</span>
                        <svg class="w-5 h-5 text-white/80 transform group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path></svg>
                    </div>
                </a>
            </div>

            <!-- Manual Generator -->
            <div class="pt-6 border-t border-slate-700/80">
                <h3 class="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
                    <span>⚡ Offline Activation Generator</span>
                </h3>
                <form action="/admin/manual_generate" method="POST" class="bg-slate-800/80 p-5 rounded-2xl border border-slate-700/80 shadow-inner flex flex-col gap-4">
                    <input type="hidden" name="pwd" value="{pwd}">
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Machine ID</label>
                        <input type="text" name="machine_id" required placeholder="e.g. 3A60F7EB" class="w-full font-mono text-sm px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-red-500 focus:outline-none">
                    </div>
                    
                    <div>
                        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">Plan Duration</label>
                        <select name="days" class="w-full text-sm px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-red-500 focus:outline-none">
                            <option value="30">1 Month (30 Days)</option>
                            <option value="60" selected>2 Months (60 Days)</option>
                            <option value="90">3 Months (90 Days)</option>
                        </select>
                    </div>
                    
                    <button type="submit" class="w-full mt-1 bg-red-600 hover:bg-red-700 text-white font-bold py-3 rounded-xl transition-all shadow-lg shadow-red-600/30 flex items-center justify-center gap-2 text-sm active:scale-98">
                        Generate Short Activation Code
                    </button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.route("/admin/users", methods=["GET"])
def admin_users():
    pwd = request.args.get("pwd")
    if pwd != ADMIN_PASSWORD:
        return f"""
        <html>
        {HTML_HEAD}
        <body class="min-h-screen flex items-center justify-center p-4">
            <div class="glass-panel w-full max-w-sm rounded-3xl p-8 text-center text-white">
                <h3 class="text-xl font-bold text-white mb-2">Admin Portal</h3>
                <form class="flex flex-col gap-3">
                    <input type="password" name="pwd" placeholder="Enter Password" class="w-full text-center px-4 py-3 bg-slate-800 border border-slate-700 text-white rounded-xl focus:outline-none text-sm">
                    <button type="submit" class="w-full bg-red-600 text-white font-semibold py-3 rounded-xl text-sm">Sign In</button>
                </form>
            </div>
        </body>
        </html>
        """

    now_ts = int(time.time())
    rows_html = ""
    total_users = 0

    try:
        docs = sb_query("active_licenses", "status", "eq", "active")
        total_users = len(docs)
        for p in docs:
            days = int(p.get("days", 30))
            raw_created = p.get("created_at")
            created_ts = now_ts
            date_display = "Recently"
            if isinstance(raw_created, str):
                try:
                    clean_iso = raw_created.replace('Z', '+00:00')
                    dt = datetime.fromisoformat(clean_iso)
                    created_ts = int(dt.timestamp())
                    date_display = dt.strftime("%d %b %Y, %I:%M %p")
                except Exception:
                    created_ts = now_ts

            raw_expires = p.get("expires_at")
            if isinstance(raw_expires, (int, float)):
                expires_at = int(raw_expires)
            elif isinstance(raw_expires, str):
                try:
                    clean_iso = raw_expires.replace('Z', '+00:00')
                    expires_at = int(datetime.fromisoformat(clean_iso).timestamp())
                except Exception:
                    expires_at = created_ts + (days * 86400)
            else:
                expires_at = created_ts + (days * 86400)

            diff_seconds = max(0, expires_at - now_ts)
            days_left = (diff_seconds + 86399) // 86400
            hours_left = (diff_seconds % 86400) // 3600

            if days_left > 7:
                badge = f'<span class="inline-flex items-center gap-1.5 px-3 py-1 bg-emerald-500/20 text-emerald-400 rounded-full text-xs font-bold border border-emerald-500/30"><span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> {days_left} Days Left</span>'
            elif days_left > 0:
                badge = f'<span class="inline-flex items-center gap-1.5 px-3 py-1 bg-amber-500/20 text-amber-400 rounded-full text-xs font-bold border border-amber-500/30">⚡ {days_left}d {hours_left}h Left</span>'
            else:
                badge = f'<span class="inline-flex items-center gap-1.5 px-3 py-1 bg-red-500/20 text-red-400 rounded-full text-xs font-bold border border-red-500/30">🔴 Expiring Today</span>'

            rows_html += f"""
            <tr class="user-row border-b border-slate-800/80 hover:bg-slate-800/40 transition-colors" data-search="{p.get('nickname','').lower()} {p.get('machine_id','').lower()}">
                <td class="px-6 py-4">
                    <div class="flex items-center gap-3">
                        <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center font-bold text-white text-sm shadow-md">
                            {p.get('nickname', 'U')[0].upper()}
                        </div>
                        <div>
                            <div class="font-bold text-white text-sm">{p.get('nickname', 'ReconX Pro User')}</div>
                            <div class="text-[11px] text-slate-400 font-mono">Order: {p.get('order_id', 'N/A')}</div>
                        </div>
                    </div>
                </td>
                <td class="px-6 py-4">
                    <div class="flex items-center gap-2">
                        <span class="font-mono text-xs font-bold text-emerald-400 bg-slate-900 px-2.5 py-1 rounded-lg border border-slate-800">{p.get('machine_id')}</span>
                        <button onclick="navigator.clipboard.writeText('{p.get('machine_id')}'); alert('Machine ID copied!');" class="p-1 text-slate-400 hover:text-white" title="Copy">
                            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
                        </button>
                    </div>
                </td>
                <td class="px-6 py-4">
                    <span class="px-2.5 py-1 rounded-lg bg-indigo-500/20 text-indigo-300 font-mono text-xs font-semibold border border-indigo-500/30">{p.get('days')} Days</span>
                </td>
                <td class="px-6 py-4">
                    {badge}
                </td>
                <td class="px-6 py-4 text-xs text-slate-400">
                    {date_display}
                </td>
                <td class="px-6 py-4 text-right">
                    <form action="/admin/revoke" method="POST" class="inline m-0" onsubmit="return confirm('Are you sure you want to revoke license for {p.get('nickname')}?');">
                        <input type="hidden" name="pwd" value="{pwd}">
                        <input type="hidden" name="doc_id" value="{p.get('id')}">
                        <button type="submit" class="px-3 py-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 rounded-xl text-xs font-bold border border-red-500/30 transition-colors">
                            Revoke
                        </button>
                    </form>
                </td>
            </tr>
            """
    except Exception as e:
        rows_html = f'<tr><td colspan="6" class="p-6 text-center text-red-400 text-xs">Error loading users: {e}</td></tr>'

    if not rows_html:
        rows_html = '<tr><td colspan="6" class="p-12 text-center text-slate-500 text-sm">No active licenses found in the system.</td></tr>'

    return f"""
    <html>
    {HTML_HEAD}
    <body class="min-h-screen p-4 md:p-8 flex justify-center text-white">
        <div class="glass-panel w-full max-w-6xl rounded-3xl p-6 md:p-8 h-fit">
            
            <!-- Top Nav -->
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8 border-b border-slate-700/80 pb-6">
                <div>
                    <a href="/admin?pwd={pwd}" class="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors mb-2">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path></svg>
                        Back to Overview
                    </a>
                    <h2 class="text-2xl font-black text-white flex items-center gap-3">
                        <span>Active License Directory</span>
                        <span class="px-3 py-1 bg-emerald-500/20 text-emerald-400 rounded-full text-xs font-mono border border-emerald-500/30 font-bold">{total_users} Active</span>
                    </h2>
                </div>

                <div class="flex items-center gap-3">
                    <input type="text" id="userSearch" onkeyup="filterUsers()" placeholder="Search user or machine ID..." class="px-4 py-2.5 bg-slate-900 border border-slate-700 rounded-xl text-white placeholder-slate-500 text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none w-64">
                    <a href="/admin/users?pwd={pwd}" class="px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-xl text-xs font-semibold border border-slate-700 transition-colors flex items-center gap-1.5">
                        🔄 Refresh
                    </a>
                </div>
            </div>

            <!-- Full Width Table -->
            <div class="overflow-x-auto rounded-2xl border border-slate-800">
                <table class="w-full text-left border-collapse">
                    <thead>
                        <tr class="bg-slate-900/80 border-b border-slate-800 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                            <th class="px-6 py-4">User / Nickname</th>
                            <th class="px-6 py-4">Machine ID</th>
                            <th class="px-6 py-4">Plan</th>
                            <th class="px-6 py-4">Time Left</th>
                            <th class="px-6 py-4">Activated On</th>
                            <th class="px-6 py-4 text-right">Action</th>
                        </tr>
                    </thead>
                    <tbody id="userTableBody">
                        {rows_html}
                    </tbody>
                </table>
            </div>

        </div>

        <script>
            function filterUsers() {{
                const query = document.getElementById('userSearch').value.toLowerCase();
                const rows = document.querySelectorAll('.user-row');
                rows.forEach(row => {{
                    const text = row.getAttribute('data-search') || '';
                    if (text.includes(query)) {{
                        row.style.display = '';
                    }} else {{
                        row.style.display = 'none';
                    }}
                }});
            }}
        </script>
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

    # Redirect back to user directory
    return f"""
    <html>
    <head><meta http-equiv="refresh" content="0; url=/admin/users?pwd={pwd}" /></head>
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
