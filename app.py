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
import hashlib

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

@app.route('/api/extract-text', methods=['POST'])
@auth.login_required
def extract_text():
    """Extract text from PDF and return structured JSON"""
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Read file content
        pdf_data = file.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        # Initialize result dictionary
        result = {}
        
        # Process each page
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Extract text blocks with hierarchical information
            blocks = page.get_text("dict")["blocks"]
            
            # Process blocks
            for block in blocks:
                # Check if this is a text block
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if text:
                                # Create a unique ID for this text
                                text_id = hashlib.md5(text.encode()).hexdigest()
                                
                                # Determine text type based on formatting or context
                                font_size = span["size"]
                                font_name = span["font"]
                                is_bold = "bold" in font_name.lower() or span["flags"] & 2 > 0
                                
                                # Simple heuristics for text type classification
                                if is_bold or font_size > 10:
                                    text_type = "Title"
                                elif block.get("type", 0) == 1:  # Image block with text
                                    text_type = "Image"
                                elif len(text.split()) > 20:
                                    text_type = "NarrativeText"
                                else:
                                    text_type = "UncategorizedText"
                                
                                # Identify parent text (e.g., header for a field)
                                parent_id = None
                                if text_type == "UncategorizedText" and len(result) > 0:
                                    # This is a very simplified way to identify parent-child relationships
                                    # For more accurate results, you'd need to analyze spatial relationships
                                    for prev_id, prev_item in result.items():
                                        if prev_item["type"] == "Title" and prev_item["metadata"]["page_number"] == page_num + 1:
                                            parent_id = prev_id
                                            break
                                
                                # Create metadata
                                metadata = {
                                    "filetype": "application/pdf",
                                    "languages": ["eng"],  # Assuming English, add language detection if needed
                                    "page_number": page_num + 1,
                                    "filename": file.filename
                                }
                                
                                if parent_id:
                                    metadata["parent_id"] = parent_id
                                
                                # Add to result
                                result[text_id] = {
                                    "type": text_type,
                                    "text": text,
                                    "metadata": metadata
                                }
                
                # Check if this is a table block
                elif block.get("type", 0) == 1 and "image" in block:
                    # Handle table as image (simplified approach)
                    table_id = hashlib.md5(f"table_{page_num}_{block['bbox']}".encode()).hexdigest()
                    
                    # Extract table text if available
                    table_text = ""
                    table_rect = fitz.Rect(block["bbox"])
                    table_text = page.get_text("text", clip=table_rect)
                    
                    # Create HTML representation (simplified)
                    html_text = f"<table><tbody><tr><td>{table_text}</td></tr></tbody></table>"
                    
                    result[table_id] = {
                        "type": "Table",
                        "text": table_text.strip(),
                        "metadata": {
                            "text_as_html": html_text,
                            "filetype": "application/pdf",
                            "languages": ["eng"],
                            "page_number": page_num + 1,
                            "filename": file.filename
                        }
                    }
        
        # Wrap in array as per example
        final_result = [result]
        
        return jsonify(final_result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
            # Use pdfplumber coords directly (top-left origin, y increasing downward)
            x0 = float(loc.get('x0', 0))
            y0 = float(loc.get('y0', 0))
            x1 = float(loc.get('x1', 0))
            y1 = float(loc.get('y1', 0))
            rect = fitz.Rect(x0, y0, x1, y1)
            page.add_redact_annot(rect, fill=(1, 1, 1))
        # Commit all redactions
        for p in pdf:
            p.apply_redactions()
        # 4) Return stripped PDF
        out = io.BytesIO()
        pdf.save(out, deflate=True)
        pdf.close()
        out.seek(0)
        return send_file(out, mimetype="application/pdf", as_attachment=True, download_name="redacted.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
