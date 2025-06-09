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

# Ensure that both API_USERNAME and API_PASSWORD are set
if not API_USERNAME or not API_PASSWORD:
    raise ValueError("API_USERNAME and API_PASSWORD environment variables must be set.")

users = {
    API_USERNAME: generate_password_hash(API_PASSWORD)
}

@auth.verify_password
def verify_password(username, password):
    return username in users and check_password_hash(users.get(username), password)

# ... (all your existing routes here) ...

# --- PDF to Image Endpoints ---

@app.route('/api/pdf_to_image', methods=['POST'])
@auth.login_required
def pdf_to_image():
    """
    Converts a specific page of a PDF to a high-DPI PNG image (default: 300 DPI).
    POST with 'pdf_file', optional 'page_number' (1-based), and optional 'dpi'.
    Returns: PNG image.
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        # Params
        page_number = request.form.get('page_number', default=1, type=int)
        dpi = request.form.get('dpi', default=300, type=int)
        if dpi < 72 or dpi > 1200:
            return jsonify({"error": "DPI must be between 72 and 1200"}), 400

        pdf = fitz.open(stream=file.read(), filetype="pdf")
        if page_number < 1 or page_number > pdf.page_count:
            return jsonify({"error": f"Page_number out of bounds (1-{pdf.page_count})"}), 400

        page = pdf.load_page(page_number - 1)
        scale = dpi / 72  # 72 is the default PDF DPI
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Save as PNG to buffer
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
    """
    Converts all pages of a PDF to high-DPI PNG images and returns them as a zip.
    POST with 'pdf_file' and optional 'dpi'.
    Returns: ZIP of PNGs.
    """
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

# --- End PDF to Image Endpoints ---

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
