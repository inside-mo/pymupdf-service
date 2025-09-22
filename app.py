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
import traceback  # Add this import for error reporting
import re  # Add this import for regular expressions

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

@app.route('/api/extract_pages', methods=['POST'])
@auth.login_required
def extract_pages():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    page_start = request.form.get('page_start', type=int)
    page_end = request.form.get('page_end', type=int)
    if page_start is None or page_end is None:
        return jsonify({"error": "Both page_start and page_end must be provided"}), 400
    if page_start < 1 or page_end < 1:
        return jsonify({"error": "page_start and page_end must be positive integers"}), 400
    if page_start > page_end:
        return jsonify({"error": "page_start cannot be greater than page_end"}), 400
    try:
        # Open the original PDF
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        total_pages = pdf.page_count
        # Adjust page_end if it exceeds total_pages
        if page_end > total_pages:
            page_end = total_pages
        # Create a new PDF to hold the extracted pages
        new_pdf = fitz.open()
        for page_num in range(page_start, page_end + 1):
            new_pdf.insert_pdf(pdf, from_page=page_num - 1, to_page=page_num - 1)  # Zero-based indexing
        # Prepare the PDF to be returned
        pdf_stream = io.BytesIO()
        new_pdf.save(pdf_stream)  # Save to an in-memory stream
        new_pdf.close()
        pdf_stream.seek(0)  # Reset stream position to the beginning
        return send_file(pdf_stream, as_attachment=True, download_name="extracted_pages.pdf", mimetype='application/pdf')
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6000, debug=True)

@app.route('/api/extract-text', methods=['POST'])
@auth.login_required
def extract_text():
    """Extract structured text from PDF with page ordering"""
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        # Read file content
        pdf_data = file.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        # Initialize ordered result dictionary
        ordered_result = {}
        
        # Process each page
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_key = f"page_{page_num + 1}"
            ordered_result[page_key] = {
                "page_number": page_num + 1,
                "content": {}
            }
            
            # Extract text as plain text for debugging
            plain_text = page.get_text("text")
            debug_id = hashlib.md5(f"debug_page_{page_num}".encode()).hexdigest()
            ordered_result[page_key]["content"][debug_id] = {
                "type": "Debug",
                "text": plain_text,
                "metadata": {
                    "filetype": "application/pdf",
                    "page_number": page_num + 1,
                    "filename": file.filename
                }
            }
            
            # Get text with structure information
            text_dict = page.get_text("dict")
            
            # Track labels to identify field types
            labels = {}  # Store label text -> position mapping
            
            # First pass: identify labels (likely field names)
            for block_idx, block in enumerate(text_dict["blocks"]):
                if "lines" in block:
                    for line_idx, line in enumerate(block["lines"]):
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if text.endswith(":") or (len(text) < 30 and text.isupper()):
                                # This is likely a label
                                label_key = text.rstrip(":")
                                labels[label_key] = {
                                    "bbox": line["bbox"],
                                    "page": page_num,
                                    "block": block_idx
                                }
            
            # Second pass: extract all text blocks with type classification
            for block_idx, block in enumerate(text_dict["blocks"]):
                if "lines" in block:
                    # Look for potential address patterns
                    block_text = " ".join([
                        span["text"] 
                        for line in block["lines"] 
                        for span in line["spans"]
                    ])
                    
                    # Identify address patterns (postal code patterns in European format)
                    address_pattern = r'\b\d{4,5}[\s,]\s*\w+'
                    is_likely_address = bool(re.search(address_pattern, block_text))
                    
                    # Identify date patterns
                    date_pattern = r'\b\d{1,2}[.-]\d{1,2}[.-]\d{2,4}\b'
                    has_date = bool(re.search(date_pattern, block_text))
                    
                    # Process each line
                    for line_idx, line in enumerate(block["lines"]):
                        line_text = " ".join([span["text"] for span in line["spans"]])
                        
                        # Skip empty lines
                        if not line_text.strip():
                            continue
                        
                        # Create a unique ID for the line
                        line_id = hashlib.md5(f"{page_num}_{block_idx}_{line_idx}_{line_text}".encode()).hexdigest()
                        
                        # Determine if this line is a value for a label
                        label_match = None
                        for label, info in labels.items():
                            if (info["page"] == page_num and 
                                info["block"] == block_idx and
                                abs(line["bbox"][1] - info["bbox"][3]) < 15):
                                label_match = label
                                break
                        
                        # Classify text types based on patterns and structure
                        text_type = "UncategorizedText"
                        metadata = {
                            "filetype": "application/pdf",
                            "page_number": page_num + 1,
                            "filename": file.filename,
                            "bbox": line["bbox"]  # Adding bounding box information
                        }
                        
                        # Use font properties
                        font_props = line["spans"][0] if line["spans"] else None
                        is_bold = font_props and (font_props.get("flags", 0) & 2 > 0)
                        font_size = font_props["size"] if font_props else 0
                        
                        # Determine text type based on features
                        if is_likely_address and re.search(r'\d', line_text):
                            text_type = "Address"
                        elif has_date and re.search(date_pattern, line_text):
                            text_type = "Date"
                        elif re.search(r'GmbH|AG|Co\.|Inc\.|Ltd\.', line_text):
                            text_type = "Organization"
                        elif is_bold or font_size > 10:
                            text_type = "Title"
                        elif label_match:
                            text_type = "FieldValue"
                            metadata["field_name"] = label_match
                        elif len(line_text.split()) > 10:
                            text_type = "NarrativeText"
                        
                        # Add to page-specific results
                        ordered_result[page_key]["content"][line_id] = {
                            "type": text_type,
                            "text": line_text.strip(),
                            "metadata": metadata
                        }
                        
                        # Process individual spans
                        for span_idx, span in enumerate(line["spans"]):
                            span_text = span["text"].strip()
                            if not span_text or span_text == line_text.strip():
                                continue
                            
                            span_id = hashlib.md5(f"{page_num}_{block_idx}_{line_idx}_{span_idx}_{span_text}".encode()).hexdigest()
                            
                            span_type = "UncategorizedText"
                            if span.get("flags", 0) & 2 > 0 or span.get("size", 0) > 10:
                                span_type = "Title"
                            
                            ordered_result[page_key]["content"][span_id] = {
                                "type": span_type,
                                "text": span_text,
                                "metadata": {
                                    "filetype": "application/pdf",
                                    "page_number": page_num + 1,
                                    "filename": file.filename,
                                    "parent_line": line_id,
                                    "bbox": span["bbox"]  # Adding span bounding box
                                }
                            }
            
            # Extract tables (if present)
            try:
                for block_idx, block in enumerate(text_dict["blocks"]):
                    if "lines" in block and len(block["lines"]) > 3:
                        line_structures = []
                        for line in block["lines"]:
                            line_text = " ".join([span["text"] for span in line["spans"]])
                            pattern = ""
                            for part in re.findall(r'[\d.]+|\w+|[^\w\s]', line_text):
                                if re.match(r'^\d+(\.\d+)?$', part):
                                    pattern += "N"
                                elif re.match(r'^[A-Za-z]+$', part):
                                    pattern += "T"
                                else:
                                    pattern += "S"
                            line_structures.append(pattern)
                        
                        if len(set(line_structures)) < len(line_structures) / 2:
                            table_id = hashlib.md5(f"table_{page_num}_{block_idx}".encode()).hexdigest()
                            ordered_result[page_key]["content"][table_id] = {
                                "type": "Table",
                                "text": "\n".join([
                                    " | ".join([span["text"] for span in line["spans"]]) 
                                    for line in block["lines"]
                                ]),
                                "metadata": {
                                    "filetype": "application/pdf",
                                    "page_number": page_num + 1,
                                    "filename": file.filename,
                                    "bbox": block["bbox"]  # Adding table bounding box
                                }
                            }
            except Exception as table_error:
                table_error_id = hashlib.md5(f"table_error_{page_num}".encode()).hexdigest()
                ordered_result[page_key]["content"][table_error_id] = {
                    "type": "Error",
                    "text": f"Table extraction error: {str(table_error)}",
                    "metadata": {
                        "filetype": "application/pdf",
                        "page_number": page_num + 1,
                        "filename": file.filename
                    }
                }
        
        return jsonify(ordered_result)
    
    except Exception as e:
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

def has_mark_in_area(pixmap):
    # Convert pixmap to bytes and analyze for dark pixels
    # You might need to adjust these thresholds
    samples = pixmap.samples
    pixel_count = 0
    dark_threshold = 200  # Adjust based on your PDF
    
    for i in range(0, len(samples), pixmap.n):
        if samples[i] < dark_threshold:  # For grayscale
            pixel_count += 1
    
    return pixel_count > (pixmap.width * pixmap.height * 0.1)  # 10% threshold

@app.route('/api/get-checkboxes', methods=['POST'])
@auth.login_required
def get_checkboxes():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        checkbox_content = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # 1. Try widget detection (existing)
            fields = page.widgets()
            
            # 2. Add visual detection for specific text patterns
            text_blocks = page.get_text("dict")["blocks"]
            for block in text_blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        text = " ".join(span["text"] for span in line["spans"])
                        # Look for your specific options
                        if text in ["Wartung erfolgreich", "Kein Zugang", "Standort existiert nicht"]:
                            # Get the surrounding area
                            rect = fitz.Rect(line["bbox"])
                            # Check for marks in the area left of the text
                            left_area = fitz.Rect(rect.x0 - 20, rect.y0, rect.x0, rect.y1)
                            
                            # Get pixel data for the checkbox area
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=left_area)
                            # Analyze pixels for marks (simplified)
                            if has_mark_in_area(pix):
                                checkbox_content.append({
                                    'name': text,
                                    'value': True,
                                    'y_pos': rect.y0,
                                    'x_pos': rect.x0,
                                    'page': page_num + 1,
                                    'detection_method': 'visual'
                                })
        
        doc.close()  # Make sure to close the document
        return jsonify(checkbox_content)
        
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

@app.route('/api/extract-all-fields', methods=['POST'])
@auth.login_required
def extract_all_fields():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['pdf_file']
    
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        results = {}
        
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            
            for i, block in enumerate(blocks):
                if "lines" not in block:
                    continue
                    
                for line in block["lines"]:
                    text = " ".join(span["text"] for span in line["spans"]).strip()
                    
                    # Case 1: Numbered items
                    if re.match(r'^\d+\.\d+\.\d+\s', text):
                        label = text
                        value = find_checkbox_value(blocks, line["bbox"])
                        if value:
                            results[label] = value
                            
                    # Case 2: Question/Comment fields (ending with colon)
                    elif text.endswith(':'):
                        label = text.rstrip(':')
                        # Look for answer in next block or lines
                        value = find_field_value(blocks, i, line["bbox"])
                        if value:
                            results[label] = value
                            
                    # Case 3: "Bemerkungen" fields
                    elif text.startswith('Bemerkungen'):
                        label = text
                        value = find_field_value(blocks, i, line["bbox"])
                        if value:
                            results[label] = value
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def find_checkbox_value(blocks, label_bbox):
    """Find closest OK/Nicht OK value to the label"""
    y_pos = label_bbox[1]
    possible_values = ["OK", "Nicht OK", "Nicht notwendig"]
    
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                text = " ".join(span["text"] for span in line["spans"])
                if any(val in text for val in possible_values):
                    if abs(line["bbox"][1] - y_pos) < 20:
                        for val in possible_values:
                            if val in text:
                                return val
    return None

def find_field_value(blocks, current_block_idx, label_bbox):
    """Find field value in subsequent text"""
    y_pos = label_bbox[1]
    value_text = []
    
    # Look in next few blocks
    for i in range(current_block_idx + 1, min(current_block_idx + 3, len(blocks))):
        block = blocks[i]
        if "lines" not in block:
            continue
            
        for line in block["lines"]:
            text = " ".join(span["text"] for span in line["spans"]).strip()
            # Skip if this looks like another label
            if text.endswith(':') or re.match(r'^\d+\.\d+\.\d+\s', text):
                break
            if text and abs(line["bbox"][1] - y_pos) < 50:  # adjust distance as needed
                value_text.append(text)
    
    return " ".join(value_text) if value_text else None
    
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
