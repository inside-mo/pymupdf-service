from flask import Flask, request, jsonify, render_template_string, send_file
import fitz  # PyMuPDF
import io
from PIL import Image
import base64
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import os

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
                next_start_page = toc[i + 1][2]  # Get the start page of the next chapter
                current_page = pdf.load_page(start_page - 1)  # Load current page (0-based index)
                current_text = current_page.get_text("text").strip()
                lines = current_text.split('\n')  # Split the current page text into lines

                title_found = False
                text_above_title = False

                # Check for the title and any text above it
                for line in lines:
                    if title in line:  # Check if we have found the chapter title
                        title_found = True
                        break
                    elif line.strip():  # If there's any preceding non-empty line
                        text_above_title = True  # Indicates there is content above the title

                if title_found:
                    if text_above_title:
                        end_page = start_page  # End page is the same as the current page if text is above
                    else:
                        end_page = start_page - 1  # End page is the previous page if no text is above
                else:
                    continue  # If no title found, we skip this iteration

            else:
                # For the last chapter; set end to the total number of pages in the document
                end_page = pdf.page_count
            
            # Ensure that end page is not before start page
            if end_page is not None and end_page < start_page:
                end_page = start_page
            
            # Append the chapter details to the outline
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
    app.run(host='0.0.0.0', port=5000, debug=True)
