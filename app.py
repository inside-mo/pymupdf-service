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

@app.route('/api/extract_table_data', methods=['POST'])
@auth.login_required
def extract_table_data():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        table_data = []

        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            # Extract text blocks with layout information
            blocks = page.get_text("blocks")

            # --- Heuristic Table Detection and Data Extraction (Adapt this!) ---
            # This is a simplified example and WILL require customization
            # based on the specific structure of your tables.

            # Example: Assuming tables are defined by consistent vertical alignment
            # and a minimum number of columns

            potential_table = [] # List of rows
            current_row = []
            last_y = None # Track vertical position

            for block in blocks:
                try:
                    x0, y0, x1, y1, text, block_no = block[:6]  # Take only the first 6 elements
                except ValueError as e:
                    print(f"Error unpacking: {block}.  Error was: {e}") # for debug
                    continue # Skip the rest of the loop, consider logging instead


                if last_y is None or abs(y0 - last_y) < 5: # Adjust tolerance as needed
                    current_row.append(text.strip())
                else:
                    #New row starts, save previous if not empty
                    if current_row:
                        potential_table.append(current_row)
                    current_row = [text.strip()]

                last_y = y0
            if current_row: #Append the last row
                potential_table.append(current_row)

            #Filter out tables with too few rows or columns
            if len(potential_table)>2 and len(potential_table[0]) > 1:
              table_data.append({"page": page_num + 1, "table": potential_table})


        return jsonify({"page_count": pdf.page_count, "tables": table_data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/extract_form_data', methods=['POST'])
@auth.login_required
def extract_form_data():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        pdf_content = file.read()
        pdf = fitz.open(stream=pdf_content, filetype="pdf")
        result = {}
        
        # Process each page
        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            
            # Extract form metadata
            text = page.get_text()
            
            # Basic Form Details
            form_data = {
                "document_type": "DGUV V3 Prüfprotokoll",
                "date": None,
                "client": None,
                "contractor": None,
                "inspection_tables": {}
            }
            
            # Extract date (simple regex approach)
            import re
            date_match = re.search(r'Datum:\s*(\d{2}\.\d{2}\.\d{4})', text)
            if date_match:
                form_data["date"] = date_match.group(1)
            
            # Extract client/contractor details
            if "Deutsche Glasfaser" in text:
                form_data["client"] = "Deutsche Glasfaser Wholesale GmbH"
            if "Tempton Technik GmbH" in text:
                form_data["contractor"] = "Tempton Technik GmbH"
            
            # Extract checkmark data from the form
            # Get precise positions of text and symbols
            blocks_dict = page.get_text("dict")
            
            # Define checkmark symbols
            checkmark_symbols = ["✓", "■", "√"]
            
            # Extract inspection tables - we need to identify table rows and columns
            inspection_tables = {
                "besichtigung": {
                    "rows": [],
                    "columns": ["i.o", "n.i.o", "t.n.z"]
                },
                "erprobung": {
                    "rows": [],
                    "columns": ["i.o", "n.i.o", "t.n.z"]
                }
            }
            
            # First find table labels to establish boundaries
            table_boundaries = {}
            for block in blocks_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        line_text = "".join([span["text"] for span in line["spans"]])
                        # Look for table headers
                        if "Besichtigung" in line_text:
                            table_boundaries["besichtigung_y"] = line["bbox"][1]
                        elif "Erprobung" in line_text:
                            table_boundaries["erprobung_y"] = line["bbox"][1]
            
            # Process all text elements to find checkmarks and row labels
            current_table = None
            checkmark_positions = []
            table_rows = {}
            
            # Find all checkmarks first
            for block in blocks_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"]
                            # Check if this span contains any checkmark symbols
                            for char in span["chars"]:
                                if char["c"] in checkmark_symbols:
                                    checkmark_positions.append({
                                        "symbol": char["c"],
                                        "x": char["bbox"][0],
                                        "y": char["bbox"][1],
                                        "width": char["bbox"][2] - char["bbox"][0],
                                        "height": char["bbox"][3] - char["bbox"][1]
                                    })
            
            # Now process all text to find row labels
            for block in blocks_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        line_text = "".join([span["text"] for span in line["spans"]])
                        y_pos = line["bbox"][1]
                        
                        # Skip if this is a table header or empty line
                        if "Besichtigung" in line_text or "Erprobung" in line_text or not line_text.strip():
                            continue
                        
                        # Determine which table this belongs to
                        if "besichtigung_y" in table_boundaries and y_pos > table_boundaries["besichtigung_y"]:
                            if "erprobung_y" in table_boundaries and y_pos > table_boundaries["erprobung_y"]:
                                current_table = "erprobung"
                            else:
                                current_table = "besichtigung"
                                
                        if current_table:
                            # Filter out header texts like "i.o", "n.i.o", "t.n.z"
                            if line_text.strip() not in ["i.o", "n.i.o", "t.n.z", "Bemerkung:"]:
                                # This is likely a row label
                                if line_text.strip():
                                    # Store the row with its y-position for later matching with checkmarks
                                    if current_table not in table_rows:
                                        table_rows[current_table] = []
                                    
                                    # Skip rows that are headers or don't contain inspection items
                                    skip_texts = ["Besichtigung", "Erprobung", "i.o", "n.i.o", "t.n.z", 
                                                 "Bemerkung", "siehe Checkliste"]
                                    
                                    if not any(skip_text in line_text for skip_text in skip_texts):
                                        table_rows[current_table].append({
                                            "text": line_text.strip(),
                                            "y_min": line["bbox"][1],
                                            "y_max": line["bbox"][3],
                                            "x_min": line["bbox"][0],
                                            "x_max": line["bbox"][2]
                                        })
            
            # Now build the structured data by matching checkmarks to rows
            # Define column boundaries (x-coordinates) for i.o, n.i.o, t.n.z
            # These will need to be adjusted based on your specific form layout
            column_boundaries = {
                "besichtigung": {
                    "i.o": {"min": 40, "max": 80},
                    "n.i.o": {"min": 80, "max": 120},
                    "t.n.z": {"min": 120, "max": 160}
                },
                "erprobung": {
                    "i.o": {"min": 450, "max": 490},
                    "n.i.o": {"min": 490, "max": 530},
                    "t.n.z": {"min": 530, "max": 570}
                }
            }
            
            # Create structured tables
            for table_name in ["besichtigung", "erprobung"]:
                if table_name in table_rows:
                    for row_data in table_rows[table_name]:
                        row_item = {
                            "label": row_data["text"],
                            "i.o": False,
                            "n.i.o": False,
                            "t.n.z": False
                        }
                        
                        # Check if any checkmarks correspond to this row
                        for checkmark in checkmark_positions:
                            # Check if the checkmark's y-coordinate is within this row's range
                            if row_data["y_min"] <= checkmark["y"] <= row_data["y_max"]:
                                # Determine which column this checkmark belongs to
                                for column in ["i.o", "n.i.o", "t.n.z"]:
                                    if (column_boundaries[table_name][column]["min"] <= 
                                        checkmark["x"] <= 
                                        column_boundaries[table_name][column]["max"]):
                                        row_item[column] = True
                        
                        inspection_tables[table_name]["rows"].append(row_item)
            
            form_data["inspection_tables"] = inspection_tables
            
            # Extract circuit table data
            circuit_table = []
            # Logic to extract circuit table rows would go here
            # This is more complex and would need careful coordinates mapping
            
            result[page_num + 1] = form_data
        
        return jsonify({
            "page_count": pdf.page_count,
            "form_data": result
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
