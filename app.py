from flask import Flask, request, jsonify, render_template_string, send_file
import fitz  # PyMuPDF
import io
import json
from PIL import Image
import base64
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import os
import zipfile

app = Flask(__name__)
auth = HTTPBasicAuth()
# Fetching credentials from environment variables
API_USERNAME = os.environ.get("API_USERNAME")
API_PASSWORD = os.environ.get("API_PASSWORD")
# Ensure that both API_USERNAME and API_PASSWORD are set
if not API_USERNAME or not API_PASSWORD:
    raise ValueError("API_USERNAME and API_PASSWORD environment variables must be set.")
users = {
    API_USERNAME: generate_password_hash(API_PASSWORD)
}

@auth.verify_password
def verify_password(username, password):
    return username in users and check_password_hash(users.get(username), password)

# HTML template for the web interface
HTML_TEMPLATE = '''
<!doctype html>
<html>
<head>
    <title>PyMuPDF Service</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 50px; }
        h1 { color: #333; }
        form { margin-top: 20px; }
        input[type=file] { padding: 10px; }
        input[type=submit] { padding: 10px 20px; background-color: #28a745; color: white; border: none; cursor: pointer; }
        input[type=submit]:hover { background-color: #218838; }
    </style>
</head>
<body>
    <h1>Upload PDF to Process</h1>
    <form method="post" enctype="multipart/form-data">
        <input type="file" name="pdf_file" accept="application/pdf" required>
        <br><br>
        <input type="submit" value="Process">
    </form>
    {% if result %}
        <h2>Result:</h2>
        <pre>{{ result }}</pre>
    {% endif %}
</body>
</html>
'''

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'pdf_file' not in request.files:
            return "No file part", 400
        file = request.files['pdf_file']
        if file.filename == '':
            return "No selected file", 400
        try:
            pdf = fitz.open(stream=file.read(), filetype="pdf")
            num_pages = pdf.page_count
            result = f"The uploaded PDF has {num_pages} pages."
            return render_template_string(HTML_TEMPLATE, result=result)
        except Exception as e:
            return f"An error occurred while processing the PDF: {str(e)}", 500
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/redact', methods=['POST'])
@auth.login_required
def redact():
    # 1) Retrieve PDF file
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    # 2) Parse locations (support raw JSON array or form-data)
    locations = None
    if request.is_json:
        data = request.get_json()
        if isinstance(data, list):
            locations = data
        elif isinstance(data, dict) and 'locations' in data:
            locations = data['locations']
    if locations is None:
        locs_str = request.form.get('locations')
        if locs_str:
            try:
                obj = json.loads(locs_str)
                if isinstance(obj, list):
                    locations = obj
                elif isinstance(obj, dict) and 'locations' in obj:
                    locations = obj['locations']
            except Exception as e:
                return jsonify({"error": "Invalid locations JSON", "details": str(e)}), 400
    if not locations:
        return jsonify({"error": "No locations provided"}), 400

    # 3) Apply redactions
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        for loc in locations:
            page_idx = int(loc.get('page', 0))
            if page_idx < 0 or page_idx >= pdf.page_count:
                continue
            page = pdf.load_page(page_idx)
            # pdfplumber uses origin top-left (0,0 at top-left), y increasing downward
            # PyMuPDF (PDF) uses origin bottom-left (0,0 at bottom-left), y increasing upward
            x0 = float(loc.get('x0', 0)); x1 = float(loc.get('x1', 0))
            y0 = float(loc.get('y0', 0)); y1 = float(loc.get('y1', 0))
            H = float(loc.get('page_height', page.rect.height))
            # Convert from pdfplumber to PDF/PyMuPDF coords:
            #   PDF y0 = H - y1 (top of box)
            #   PDF y1 = H - y0 (bottom of box)
            top = H - y1  # PDF y0
            bottom = H - y0  # PDF y1
            rect = fitz.Rect(x0, top, x1, bottom)
            page.add_redact_annot(rect, fill=(1, 1, 1))
        # commit all redactions
        for p in pdf:
            p.apply_redactions()
        # 4) return stripped PDF
        out = io.BytesIO()
        pdf.save(out, deflate=True)
        pdf.close()
        out.seek(0)
        return send_file(out, mimetype="application/pdf", as_attachment=True, download_name="redacted.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# … other endpoints unchanged …

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
