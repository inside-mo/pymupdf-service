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
            try:
                pdf = fitz.open(stream=file.read(), filetype="pdf")
                num_pages = pdf.page_count
                result = f"The uploaded PDF has {num_pages} pages."
                return render_template_string(HTML_TEMPLATE, result=result)
            except Exception as e:
                return f"An error occurred while processing the PDF: {str(e)}", 500
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/extract_markdown', methods=['POST'])
@auth.login_required
def extract_markdown():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        markdown_text = ""
        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            markdown_text += page.get_text("markdown")
            markdown_text += "\n\n"  # Add spacing between pages
        return jsonify({
            "page_count": pdf.page_count,
            "markdown_text": markdown_text
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_random_pages', methods=['POST'])
@auth.login_required
def extract_random_pages():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    pages_str = request.form.get('pages', '')  # Get as string like "1,3,7"
    pages = [int(p) for p in pages_str.split(',')] if pages_str else []
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        extracted_text = {}
        for page_num in pages:
            page = pdf.load_page(page_num-1)
            extracted_text[page_num] = page.get_text()
        return jsonify({
            "page_count": pdf.page_count,
            "extracted_text": extracted_text
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_text', methods=['POST'])
@auth.login_required
def extract_text():
    # Retrieve the PDF file
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    # Retrieve and validate page_start and page_end
    page_start = request.form.get('page_start', type=int)
    page_end = request.form.get('page_end', type=int)
    if page_start is None or page_end is None:
        return jsonify({"error": "Both page_start and page_end must be provided"}), 400
    if page_start < 1 or page_end < 1:
        return jsonify({"error": "page_start and page_end must be positive integers"}), 400
    if page_start > page_end:
        return jsonify({"error": "page_start cannot be greater than page_end"}), 400
    try:
        # Open the PDF with PyMuPDF
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        total_pages = pdf.page_count
        # Adjust page_end if it exceeds the total number of pages
        if page_end > total_pages:
            page_end = total_pages
        extracted_text = {}
        # Extract text from the specified page range
        for page_num in range(page_start, page_end + 1):
            page = pdf.load_page(page_num - 1)  # Zero-based indexing
            text = page.get_text()
            extracted_text[page_num] = text
        return jsonify({
            "page_count": total_pages,
            "extracted_text": extracted_text
        }), 200
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/extract_images', methods=['POST'])
@auth.login_required
def extract_images():
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
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        toc = pdf.get_toc(simple=False)  # Get the outline/toc with detailed entries
        outline = []
        for i, entry in enumerate(toc):
            title = entry[1]
            start_page = entry[2]
            end_page = None
            if i + 1 < len(toc):
                next_start_page = toc[i + 1][2]  # The start page of the next chapter
                next_title = toc[i + 1][1]  # The title of the next chapter
                # Case 1: If the next chapter starts on the same page
                if next_start_page == start_page:
                    end_page = start_page  # Simply set end page to current page
                # Case 2: If the next chapter starts on a different page
                else:
                    # Load the next chapter's start page
                    next_page = pdf.load_page(next_start_page - 1)  # 0-based index
                    next_page_text = next_page.get_text("text").strip()
                    next_page_lines = next_page_text.split('\n')
                    # Check for text above the next chapter's title
                    text_above_title = False
                    for line in next_page_lines:
                        if next_title in line:  # Found the next chapter's title
                            break
                        if line.strip():  # Found text above the title
                            text_above_title = True
                            break
                    if text_above_title:
                        end_page = next_start_page  # Set to current page if text exists above
                    else:
                        end_page = next_start_page - 1  # Set to previous page if no text above
            else:
                # For the last chapter; set end to total pages of the document
                end_page = pdf.page_count
            # Ensure end page is not before start page
            if end_page is not None and end_page < start_page:
                end_page = start_page
            outline.append({
                "level": entry[0],
                "title": title,
                "start_page": start_page,
                "end_page": end_page
            })
        return jsonify({"page_count": pdf.page_count, "outline": outline}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_pages_text', methods=['POST'])
@auth.login_required
def extract_pages_text():
    # Retrieve the PDF file
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    # Retrieve and validate page_start and page_end
    page_start = request.form.get('page_start', type=int)
    page_end = request.form.get('page_end', type=int)
    if page_start is None or page_end is None:
        return jsonify({"error": "Both page_start and page_end must be provided"}), 400
    if page_start < 1 or page_end < 1:
        return jsonify({"error": "page_start and page_end must be positive integers"}), 400
    if page_start > page_end:
        return jsonify({"error": "page_start cannot be greater than page_end"}), 400
    try:
        # Open the PDF with PyMuPDF
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        total_pages = pdf.page_count
        # Adjust page_end if it exceeds the total number of pages
        if page_end > total_pages:
            page_end = total_pages
        extracted_text = {}
        for page_num in range(page_start, page_end + 1):
            page = pdf.load_page(page_num - 1)  # Zero-based indexing
            text = page.get_text()
            extracted_text[page_num] = text
        return jsonify({
            "page_count": total_pages,
            "extracted_text": extracted_text
        }), 200
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/extract_pages', methods=['POST'])
@auth.login_required
def extract_pages():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    # Check which method is being used (range or specific pages)
    page_start = request.form.get('page_start', type=int)
    page_end = request.form.get('page_end', type=int)
    pages_str = request.form.get('pages', '')
    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        total_pages = pdf.page_count
        new_pdf = fitz.open()
        # Handle page range method
        if page_start and page_end:
            if page_start < 1 or page_end < 1:
                return jsonify({"error": "page_start and page_end must be positive integers"}), 400
            if page_start > page_end:
                return jsonify({"error": "page_start cannot be greater than page_end"}), 400
            page_end = min(page_end, total_pages)
            pages = range(page_start, page_end + 1)
        # Handle specific pages method
        elif pages_str:
            pages = [int(p) for p in pages_str.split(',')]
            if not all(p > 0 for p in pages):
                return jsonify({"error": "All page numbers must be positive integers"}), 400
        else:
            return jsonify({"error": "Either page range or specific pages must be provided"}), 400
        # Extract pages
        for page_num in pages:
            if page_num <= total_pages:
                new_pdf.insert_pdf(pdf, from_page=page_num-1, to_page=page_num-1)
        # Prepare PDF for return
        pdf_stream = io.BytesIO()
        new_pdf.save(pdf_stream)
        new_pdf.close()
        pdf_stream.seek(0)
        return send_file(
            pdf_stream,
            as_attachment=True,
            download_name="extracted_pages.pdf",
            mimetype='application/pdf'
        )
    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@app.route('/api/pdf_to_image', methods=['POST'])
@auth.login_required
def pdf_to_image():
    import sys
    import mimetypes
    # Accept file from form field 'pdf_file' or raw data
    file = request.files.get('pdf_file')
    if not file or file.filename == '':
        # Try to detect raw binary POST (n8n style)
        if request.data and len(request.data) > 0:
            file_bytes = io.BytesIO(request.data)
            filename = "upload.pdf"
            mime_type = "application/pdf"
        else:
            return jsonify({"error": "No file part"}), 400
    else:
        file_bytes = io.BytesIO(file.read())
        filename = file.filename
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    # Determine DPI
    dpi = request.args.get('dpi') or request.form.get('dpi') or 300
    try:
        dpi = int(dpi)
    except Exception:
        dpi = 300
    if dpi < 72 or dpi > 1200:
        return jsonify({"error": "DPI must be between 72 and 1200"}), 400
    # Check if file is a ZIP by signature
    file_bytes.seek(0)
    sig = file_bytes.read(4)
    file_bytes.seek(0)
    if sig == b'PK\x03\x04':  # ZIP signature
        # Process as ZIP
        zip_input = zipfile.ZipFile(file_bytes)
        output_zip = io.BytesIO()
        with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for name in zip_input.namelist():
                if name.lower().endswith('.pdf'):
                    pdfdata = zip_input.read(name)
                    try:
                        pdf = fitz.open(stream=pdfdata, filetype="pdf")
                        scale = dpi / 72
                        mat = fitz.Matrix(scale, scale)
                        for i in range(pdf.page_count):
                            page = pdf.load_page(i)
                            pix = page.get_pixmap(matrix=mat, alpha=False)
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            img_bytes = io.BytesIO()
                            img.save(img_bytes, format="PNG")
                            img_bytes.seek(0)
                            img_name = f"{os.path.splitext(name)[0]}_page_{i+1}_{dpi}dpi.png"
                            zipf.writestr(img_name, img_bytes.read())
                    except Exception as e:
                        continue  # skip broken PDFs
        output_zip.seek(0)
        return send_file(
            output_zip,
            mimetype="application/zip",
            as_attachment=True,
            download_name="pdf_images.zip"
        )
    else:
        # Process as single PDF (original code)
        try:
            pdf = fitz.open(stream=file_bytes.read(), filetype="pdf")
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
