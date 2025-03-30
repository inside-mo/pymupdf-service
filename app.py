from flask import Flask, request, jsonify, render_template_string
import fitz  # PyMuPDF
import io
from PIL import Image
import base64
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

auth = HTTPBasicAuth()

users = {
    "admin": generate_password_hash("your-secure-password")
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

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
        if file:
            # Open the PDF with PyMuPDF
            try:
                pdf = fitz.open(stream=file.read(), filetype="pdf")
                # Extract the number of pages
                num_pages = pdf.page_count
                result = f"The uploaded PDF has {num_pages} pages."
                return render_template_string(HTML_TEMPLATE, result=result)
            except Exception as e:
                return f"An error occurred while processing the PDF: {str(e)}", 500
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/extract_text', methods=['POST'])
@auth.login_required
def extract_text():
    """
    Extracts all text from the uploaded PDF.
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        text = ""
        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            text += page.get_text()
        return jsonify({"page_count": pdf.page_count, "text": text}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_images', methods=['POST'])
@auth.login_required
def extract_images():
    """
    Extracts all images from the uploaded PDF and returns them as base64-encoded strings.
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        images = []
        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = pdf.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                # Encode image to base64
                encoded = base64.b64encode(image_bytes).decode('utf-8')
                images.append({
                    "page": page_num + 1,
                    "image_number": img_index + 1,
                    "extension": image_ext,
                    "data": encoded
                })
        return jsonify({"page_count": pdf.page_count, "images": images}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_metadata', methods=['POST'])
@auth.login_required
def get_metadata():
    """
    Retrieves metadata from the uploaded PDF.
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        metadata = pdf.metadata
        return jsonify({"metadata": metadata, "page_count": pdf.page_count}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/convert_page', methods=['POST'])
@auth.login_required
def convert_page():
    """
    Converts a specific page of the uploaded PDF to an image.
    Expects a 'page_number' parameter in the form data.
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    page_number = request.form.get('page_number', type=int)
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if page_number is None:
        return jsonify({"error": "No page_number provided"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        if page_number < 1 or page_number > pdf.page_count:
            return jsonify({"error": "Invalid page_number"}), 400
        page = pdf.load_page(page_number - 1)
        pix = page.get_pixmap()
        img = Image.open(io.BytesIO(pix.tobytes()))
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return jsonify({"page": page_number, "image": img_str}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_outline', methods=['POST'])
@auth.login_required
def extract_outline():
    """
    Extracts the outline of the uploaded PDF (chapters, sub-chapters, etc.).
    """
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        toc = pdf.get_toc(simple=False)  # Get the outline/toc with detailed entries
        outline = []
        for entry in toc:
            # Each entry is a list: [level, title, page number]
            outline.append({
                "level": entry[0],
                "title": entry[1],
                "page_number": entry[2]
            })
        return jsonify({"page_count": pdf.page_count, "outline": outline}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
