from flask import Flask, request, jsonify, render_template_string, send_file
import fitz  # PyMuPDF
import io
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

if not API_USERNAME or not API_PASSWORD:
    raise ValueError("API_USERNAME and API_PASSWORD environment variables must be set.")

users = {
    API_USERNAME: generate_password_hash(API_PASSWORD)
}

@auth.verify_password
def verify_password(username, password):
    return username in users and check_password_hash(users.get(username), password)

# --- PDF to Image Endpoints ---
@app.route('/api/pdf_to_image', methods=['POST'])
@auth.login_required
def pdf_to_image():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        page_number = request.form.get('page_number', default=1, type=int)
        dpi = request.form.get('dpi', default=300, type=int)
        if dpi < 72 or dpi > 1200:
            return jsonify({"error": "DPI must be between 72 and 1200"}), 400

        pdf = fitz.open(stream=file.read(), filetype="pdf")
        if page_number < 1 or page_number > pdf.page_count:
            return jsonify({"error": f"Page_number out of bounds (1-{pdf.page_count})"}), 400

        page = pdf.load_page(page_number - 1)
        scale = dpi / 72
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        return send_file(
            buf,
            mimetype="image/png",
            as_attachment=True,
            download_name=f"page_{page_number}_{dpi}dpi.png"
        )
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/pdf_to_images', methods=['POST'])
@auth.login_required
def pdf_to_images():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        dpi = request.form.get('dpi', default=300, type=int)
        if dpi < 72 or dpi > 1200:
            return jsonify({"error": "DPI must be between 72 and 1200"}), 400

        pdf = fitz.open(stream=file.read(), filetype="pdf")
        scale = dpi / 72
        mat = fitz.Matrix(scale, scale)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i in range(pdf.page_count):
                page = pdf.load_page(i)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img_bytes = io.BytesIO()
                img.save(img_bytes, format="PNG")
                img_bytes.seek(0)
                zipf.writestr(f"page_{i+1}_{dpi}dpi.png", img_bytes.read())
        zip_buf.seek(0)
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name="pdf_images.zip"
        )
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

# --- Split PDF into Single Page PDFs with Logging ---

@app.route('/api/split_pdf', methods=['POST'])
@auth.login_required
def split_pdf():
    """
    Split the uploaded PDF into single-page PDFs, return as a ZIP.
    POST with 'pdf_file'.
    """

    # --- Begin Logging Block ---
    import sys
    print("\n--- /api/split_pdf REQUEST RECEIVED ---", file=sys.stderr)
    print("Request headers:", dict(request.headers), file=sys.stderr)
    print("Request.files keys:", list(request.files.keys()), file=sys.stderr)
    print("Request.form keys:", list(request.form.keys()), file=sys.stderr)
    print("Request.files object:", request.files, file=sys.stderr)
    print("Request.form object:", request.form, file=sys.stderr)
    # If files present, print their details
    for k, v in request.files.items():
        print(f"File key: {k}, filename: {v.filename}, content_type: {v.content_type}", file=sys.stderr)
    print("--- END LOG ---\n", file=sys.stderr)
    # --- End Logging Block ---

    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part", "available_keys": list(request.files.keys())}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i in range(pdf.page_count):
                single_pdf = fitz.open()
                single_pdf.insert_pdf(pdf, from_page=i, to_page=i)
                pdf_bytes = io.BytesIO()
                single_pdf.save(pdf_bytes)
                single_pdf.close()
                pdf_bytes.seek(0)
                zipf.writestr(f"page_{i+1}.pdf", pdf_bytes.read())
        zip_buf.seek(0)
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name="split_pages.zip"
        )
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
