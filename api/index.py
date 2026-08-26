import os
import sys
import json
import smtplib
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string

# Add parent directory to python path to import tools & config
sys.path.append(str(Path(__file__).parent.parent))

from tools import read_invoices, filter_overdue, send_email, log_reminder_sent
from config import GROQ_MODEL, GROQ_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, BUSINESS_NAME, DRY_RUN
from groq import Groq

app = Flask(__name__)

# Helper to find working groq model
def get_working_groq_model(c: Groq) -> str:
    candidates = [
        "groq/compound",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
        "groq/compound-mini",
        "llama-3.3-70b-versatile"
    ]
    try:
        models = [m.id for m in c.models.list().data]
        for cand in candidates:
            if cand in models:
                return cand
        chat_models = [m for m in models if "whisper" not in m and "guard" not in m]
        if chat_models:
            return chat_models[0]
    except Exception:
        pass

    for model in candidates:
        try:
            c.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5,
            )
            return model
        except Exception:
            continue
    return GROQ_MODEL


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Follow-up Agent — MCCIA AI Studio</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0e1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --text-main: #f0f6fc;
            --text-sub: #8b949e;
            --success: #238636;
            --warning: #d29922;
            --danger: #f85149;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background-color: var(--bg-color); color: var(--text-main); min-height: 100vh; display: flex; }
        
        .sidebar {
            width: 280px;
            background: var(--card-bg);
            border-right: 1px solid var(--border-color);
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }
        .logo { width: 140px; }
        .sidebar-header h2 { font-size: 16px; font-weight: 700; color: var(--text-main); }
        .sidebar-header p { font-size: 12px; color: var(--text-sub); }
        
        .status-badge {
            background: rgba(35, 134, 54, 0.15);
            border: 1px solid rgba(35, 134, 54, 0.4);
            color: #3fb950;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .main-content { flex: 1; padding: 40px; max-width: 900px; margin: 0 auto; }
        .title-sec h1 { font-size: 26px; margin-bottom: 6px; }
        .title-sec p { color: var(--text-sub); font-size: 14px; margin-bottom: 24px; }
        
        .wizard-steps {
            display: flex;
            justify-content: space-between;
            margin-bottom: 30px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
        }
        .step-item { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text-sub); font-weight: 500; }
        .step-item.active { color: #58a6ff; font-weight: 700; }
        .step-item.done { color: #3fb950; }
        
        .card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 24px; margin-bottom: 24px; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--text-main); }
        .form-control {
            width: 100%;
            background: #0d1117;
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 14px;
        }
        .btn {
            background: var(--primary);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            width: 100%;
            transition: background 0.2s;
        }
        .btn:hover { background: var(--primary-hover); }
        
        .dropzone {
            border: 2px dashed #30363d;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            background: rgba(22, 27, 34, 0.5);
            cursor: pointer;
            transition: border 0.2s;
        }
        .dropzone:hover { border-color: #58a6ff; }
        
        .email-draft-card {
            background: #0d1117;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 16px;
        }
        .draft-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .client-info h4 { font-size: 15px; color: #58a6ff; }
        .client-info span { font-size: 12px; color: var(--text-sub); }
        
        textarea.email-body { width: 100%; height: 120px; background: #161b22; border: 1px solid var(--border-color); color: var(--text-main); padding: 10px; border-radius: 6px; font-size: 13px; margin-top: 8px; }
        
        .alert { padding: 12px 16px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; display: none; }
        .alert-danger { background: rgba(248, 81, 73, 0.15); border: 1px solid rgba(248, 81, 73, 0.4); color: #ff7b72; }
        .alert-success { background: rgba(35, 134, 54, 0.15); border: 1px solid rgba(35, 134, 54, 0.4); color: #3fb950; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h2>Payment Follow-up Agent</h2>
            <p>by MCCIA AI Studio, Pune</p>
        </div>
        <div class="status-badge">🌐 Vercel Cloud Serverless</div>
        <div style="font-size: 13px; color: var(--text-sub); margin-top: 10px;">
            <p>✅ Groq AI Connected</p>
            <p>✅ Gmail SMTP Ready</p>
            <p>✅ PDF/Excel/Word Parser</p>
        </div>
    </div>
    
    <div class="main-content">
        <div class="title-sec">
            <h1>📬 Payment Follow-up Agent</h1>
            <p>Upload invoices (Excel, CSV, PDF, Word) → AI drafts reminders → review & send</p>
        </div>
        
        <div class="wizard-steps">
            <div class="step-item active" id="step1-indicator">1. Upload File</div>
            <div class="step-item" id="step2-indicator">2. AI Drafts & Review</div>
            <div class="step-item" id="step3-indicator">3. Send Results</div>
        </div>
        
        <div id="alert-box" class="alert"></div>

        <!-- STEP 1: UPLOAD -->
        <div id="step-upload" class="card">
            <h3 style="margin-bottom: 12px; font-size: 18px;">Step 1 — Upload Invoices File</h3>
            <p style="font-size: 13px; color: var(--text-sub); margin-bottom: 20px;">
                Supports <b>Excel (.xlsx, .xls)</b>, <b>CSV (.csv)</b>, <b>PDF (.pdf)</b>, and <b>Word (.docx)</b>.
            </p>
            
            <div class="dropzone" onclick="document.getElementById('file-input').click()">
                <div style="font-size: 32px; margin-bottom: 8px;">📂</div>
                <p style="font-weight: 600;">Click to select or drag & drop file here</p>
                <p style="font-size: 12px; color: var(--text-sub); margin-top: 4px;" id="file-name-display">No file selected</p>
                <input type="file" id="file-input" style="display:none;" onchange="onFileSelected(this)">
            </div>
            
            <div class="form-group" style="margin-top: 20px;">
                <label>Send reminders for invoices overdue by at least (days):</label>
                <input type="number" id="overdue-days" class="form-control" value="7" min="1" max="90">
            </div>
            
            <button class="btn" onclick="processUpload()">🔍 Find Overdue Invoices & Generate Drafts</button>
        </div>

        <!-- STEP 2: REVIEW -->
        <div id="step-review" class="card" style="display:none;">
            <h3 style="margin-bottom: 12px; font-size: 18px;">Step 2 — Review AI Drafted Reminders</h3>
            <p style="font-size: 13px; color: var(--text-sub); margin-bottom: 20px;">
                Review each personalized reminder email drafted by Groq AI. Edit subject or body if needed before sending.
            </p>
            <div id="drafts-list"></div>
            <button class="btn" onclick="sendApprovedEmails()">📤 Send Approved Emails</button>
        </div>

        <!-- STEP 3: DONE -->
        <div id="step-done" class="card" style="display:none;">
            <h3 style="margin-bottom: 12px; font-size: 18px; color: #3fb950;">✅ Execution Completed!</h3>
            <div id="results-summary"></div>
            <button class="btn" style="margin-top: 20px;" onclick="location.reload()">🔄 Process Another File</button>
        </div>
    </div>

    <script>
        let selectedFile = null;
        let generatedDrafts = [];

        function onFileSelected(input) {
            if (input.files && input.files[0]) {
                selectedFile = input.files[0];
                document.getElementById('file-name-display').innerText = "Selected: " + selectedFile.name;
            }
        }

        function showAlert(msg, isError = true) {
            const box = document.getElementById('alert-box');
            box.innerText = msg;
            box.className = "alert " + (isError ? "alert-danger" : "alert-success");
            box.style.display = "block";
        }

        async function processUpload() {
            if (!selectedFile) {
                showAlert("Please select a file first.");
                return;
            }
            const overdueDays = document.getElementById('overdue-days').value;
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('days', overdueDays);

            showAlert("Processing file and generating AI email drafts via Groq...", false);

            try {
                const res = await fetch('/api/process-file', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.status === 'error') {
                    showAlert(data.message);
                    return;
                }
                generatedDrafts = data.drafts || [];
                if (generatedDrafts.length === 0) {
                    showAlert("✅ No overdue invoices found — all payments are on track!", false);
                    return;
                }
                renderDrafts();
                document.getElementById('step-upload').style.display = 'none';
                document.getElementById('step-review').style.display = 'block';
                document.getElementById('step1-indicator').className = 'step-item done';
                document.getElementById('step2-indicator').className = 'step-item active';
                document.getElementById('alert-box').style.display = 'none';
            } catch (err) {
                showAlert("Error processing request: " + err.message);
            }
        }

        function renderDrafts() {
            const container = document.getElementById('drafts-list');
            container.innerHTML = "";
            generatedDrafts.forEach((item, idx) => {
                const inv = item.invoice;
                container.innerHTML += `
                    <div class="email-draft-card">
                        <div class="draft-header">
                            <div class="client-info">
                                <h4>${inv.client_name || 'Client'} (${inv.invoice_no || 'N/A'})</h4>
                                <span>Amount: ₹${inv.amount} | ${inv.days_overdue} days overdue | Email: ${inv.email || 'N/A'}</span>
                            </div>
                            <label><input type="checkbox" id="send-check-${idx}" checked> Include</label>
                        </div>
                        <input type="text" class="form-control" id="subj-${idx}" value="${item.subject}">
                        <textarea class="email-body" id="body-${idx}">${item.body}</textarea>
                    </div>
                `;
            });
        }

        async function sendApprovedEmails() {
            showAlert("Dispatching emails...", false);
            let results = [];
            for (let i = 0; i < generatedDrafts.length; i++) {
                const isChecked = document.getElementById(`send-check-${i}`).checked;
                if (!isChecked) continue;

                const inv = generatedDrafts[i].invoice;
                const subj = document.getElementById(`subj-${i}`).value;
                const body = document.getElementById(`body-${i}`).value;

                try {
                    const res = await fetch('/api/send-email', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email: inv.email, subject: subj, body: body, invoice_no: inv.invoice_no, client_name: inv.client_name, amount: inv.amount, days_overdue: inv.days_overdue })
                    });
                    const d = await res.json();
                    results.push({ name: inv.client_name, invoice: inv.invoice_no, status: d.status });
                } catch(e) {
                    results.push({ name: inv.client_name, invoice: inv.invoice_no, status: 'error' });
                }
            }

            document.getElementById('step-review').style.display = 'none';
            document.getElementById('step-done').style.display = 'block';
            document.getElementById('step2-indicator').className = 'step-item done';
            document.getElementById('step3-indicator').className = 'step-item active';

            let resHtml = "";
            results.forEach(r => {
                resHtml += `<p>✅ <b>${r.name}</b> (${r.invoice}) — Status: ${r.status}</p>`;
            });
            document.getElementById('results-summary').innerHTML = resHtml;
            document.getElementById('alert-box').style.display = 'none';
        }
    </script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/process-file", methods=["POST"])
def process_file():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
    
    file_obj = request.files["file"]
    days_str = request.form.get("days", "7")
    try:
        days = int(days_str)
    except ValueError:
        days = 7

    filename = file_obj.filename or "invoices.xlsx"
    suffix = Path(filename).suffix.lower() or ".xlsx"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        file_obj.save(tmp.name)
        tmp_path = tmp.name

    raw = json.loads(read_invoices(tmp_path))
    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    if raw.get("status") == "error":
        return jsonify({"status": "error", "message": raw.get("message")}), 400

    filtered = json.loads(filter_overdue(json.dumps(raw), days))
    overdue_invoices = filtered.get("overdue_invoices", [])

    # Draft emails with Groq
    groq_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)
    groq_client = Groq(api_key=groq_key)
    working_model = get_working_groq_model(groq_client)

    drafts = []
    for inv in overdue_invoices:
        prompt = f"""Draft a professional payment reminder email.

Invoice:
- Client    : {inv.get('client_name')}
- Invoice No: {inv.get('invoice_no')}
- Amount    : ₹{inv.get('amount')}
- Overdue   : {inv.get('days_overdue')} days
- Notes     : {inv.get('notes') or 'None'}

Return ONLY a valid JSON with keys "subject" and "body".
Body rules: plain text, no markdown, open "Dear [first name],",
mention invoice no + amount, request payment in 3 working days,
close "Warm regards,\n{BUSINESS_NAME}". Under 150 words.
Return only the JSON."""
        try:
            resp = groq_client.chat.completions.create(
                model=working_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.2
            )
            raw_content = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_content)
            subj, body = data.get("subject", "Payment Reminder"), data.get("body", "")
        except Exception:
            first = str(inv.get("client_name", "Sir/Madam")).split()[0]
            subj = f"Payment Reminder: {inv.get('invoice_no')} — ₹{inv.get('amount')} Overdue"
            body = f"Dear {first},\n\nThis is a reminder that Invoice {inv.get('invoice_no')} for ₹{inv.get('amount')} is {inv.get('days_overdue')} days past due.\n\nKindly arrange payment within 3 working days.\n\nWarm regards,\n{BUSINESS_NAME}"
        
        drafts.append({"invoice": inv, "subject": subj, "body": body})

    return jsonify({"status": "ok", "drafts": drafts})

@app.route("/api/send-email", methods=["POST"])
def send_email_api():
    data = request.json or {}
    email = data.get("email", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    gmail_user = os.getenv("GMAIL_USER", GMAIL_USER)
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", GMAIL_APP_PASSWORD)
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    if dry_run or not gmail_user or not gmail_pass:
        return jsonify({"status": "dry_run_preview", "to": email})

    try:
        res = json.loads(send_email(email, subject, body))
        return jsonify(res)
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

if __name__ == "__main__":
    app.run(port=3000, debug=True)
