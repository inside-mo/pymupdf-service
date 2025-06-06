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

@app.route('/api/universal_form_extract', methods=['POST'])
@auth.login_required
def universal_form_extract():
    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        pdf_content = file.read()
        pdf = fitz.open(stream=pdf_content, filetype="pdf")
        
        # Store all extracted tables
        all_tables = []
        
        for page_num in range(pdf.page_count):
            page = pdf.load_page(page_num)
            
            # Convert to image for visual analysis
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Get all text with positions
            text_blocks = page.get_text("dict")
            
            # Extract all tables on the page
            # Step 1: Identify potential table structures
            # Look for repeating patterns or column headers like "i.o", "n.i.o", "t.n.z"
            
            form_data = {"inspection_tables": {}}
            
            # Extract all text items with their positions
            text_items = []
            for b in text_blocks["blocks"]:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            text_items.append({
                                "text": s["text"].strip(),
                                "bbox": s["bbox"],
                                "x": s["bbox"][0],
                                "y": s["bbox"][1],
                                "width": s["bbox"][2] - s["bbox"][0],
                                "height": s["bbox"][3] - s["bbox"][1]
                            })
            
            # Find potential table headers (i.o, n.i.o, t.n.z)
            header_texts = ["i.o", "n.i.o", "t.n.z"]
            potential_tables = []
            
            # Find all occurrences of header texts
            header_positions = []
            for item in text_items:
                if item["text"] in header_texts:
                    header_positions.append({
                        "text": item["text"],
                        "x": item["x"],
                        "y": item["y"],
                        "bbox": item["bbox"]
                    })
            
            # Group headers by vertical position (similar y values = same table)
            from collections import defaultdict
            tables_by_y = defaultdict(list)
            
            for header in header_positions:
                # Group headers within 20 pixels vertically
                y_key = int(header["y"] / 20) * 20
                tables_by_y[y_key].append(header)
            
            # For each group, create a potential table
            for y_key, headers in tables_by_y.items():
                # Need at least 2 headers to form a table
                if len(headers) >= 2:
                    # Sort headers by x position
                    sorted_headers = sorted(headers, key=lambda h: h["x"])
                    
                    # Create column definitions
                    columns = []
                    for header in sorted_headers:
                        columns.append({
                            "name": header["text"],
                            "x": header["x"],
                            "width": header["bbox"][2] - header["bbox"][0]
                        })
                    
                    # Define the table's vertical region (start below headers)
                    table_y_start = y_key + 20  # Start below headers
                    
                    # Find the next table or end of page
                    next_table_y = float('inf')
                    for next_y in tables_by_y.keys():
                        if next_y > y_key:
                            next_table_y = min(next_table_y, next_y)
                    
                    # If no next table found, use page height
                    if next_table_y == float('inf'):
                        table_y_end = pix.height / 2  # Convert to original coordinates
                    else:
                        table_y_end = next_table_y - 10  # End just above the next table
                    
                    potential_tables.append({
                        "columns": columns,
                        "y_start": table_y_start,
                        "y_end": table_y_end,
                        "rows": []
                    })
            
            # For each potential table, find row labels and checkboxes
            for table_idx, table in enumerate(potential_tables):
                # Find text items that could be row labels
                # These would be left of the first column and within the table's vertical region
                leftmost_x = min(col["x"] for col in table["columns"])
                
                # Find items that could be row labels
                row_labels = []
                for item in text_items:
                    # Check if item is in the table's vertical region
                    if table["y_start"] <= item["y"] <= table["y_end"]:
                        # Check if item is to the left of the first column
                        if item["x"] < leftmost_x - 5:  # Allow some margin
                            row_labels.append(item)
                
                # Group row labels by vertical position
                rows_by_y = defaultdict(list)
                for label in row_labels:
                    # Group within 10 pixels vertically
                    y_key = int(label["y"] / 10) * 10
                    rows_by_y[y_key].append(label)
                
                # Create rows
                rows = []
                for y_key, labels in rows_by_y.items():
                    # Combine labels if multiple found for a row
                    row_text = " ".join([l["text"] for l in labels])
                    if row_text.strip():  # Skip empty rows
                        row = {
                            "label": row_text,
                            "y": y_key,
                            "height": max(l["bbox"][3] for l in labels) - min(l["bbox"][1] for l in labels),
                            "column_values": {}
                        }
                        rows.append(row)
                
                # Sort rows by vertical position
                rows.sort(key=lambda r: r["y"])
                
                # Detect checkmarks in the pixel data
                checkmark_positions = []
                
                # Scan the image for potential checkmarks
                # We'll use a simple pixel density analysis
                sample_size = 8
                for row in rows:
                    row_y = row["y"] * 2  # Adjust for scaling
                    
                    for col in table["columns"]:
                        col_x = col["x"] * 2  # Adjust for scaling
                        
                        # Check pixel density in the area where a checkbox would be
                        dark_pixel_count = 0
                        for dy in range(sample_size):
                            for dx in range(sample_size):
                                try:
                                    x = int(col_x + dx)
                                    y = int(row_y + dy)
                                    pixel = img.getpixel((x, y))
                                    if sum(pixel[:3]) < 400:  # Threshold for dark pixels
                                        dark_pixel_count += 1
                                except Exception as e:
                                    pass
                        
                        # If enough dark pixels, mark as checked
                        is_checked = dark_pixel_count > (sample_size * sample_size * 0.2)  # 20% threshold
                        row["column_values"][col["name"]] = is_checked
                
                # Convert to the final format you requested
                final_rows = []
                for row in rows:
                    # Create row with ordered fields
                    final_row = {
                        "label": row["label"]
                    }
                    # Add checkbox states in order
                    for field in ["i.o", "n.i.o", "t.n.z"]:
                        final_row[field] = row["column_values"].get(field, False)
                    
                    final_rows.append(final_row)
                
                # Add to the result
                table_name = f"table_{table_idx + 1}"
                form_data["inspection_tables"][table_name] = {
                    "rows": final_rows
                }
            
            # Look for known table names in the text
            known_tables = ["besichtigung", "erprobung", "Besichtigung", "Erprobung"]
            for text_item in text_items:
                for known_table in known_tables:
                    if known_table.lower() in text_item["text"].lower():
                        # Find the closest table based on vertical position
                        closest_table_idx = None
                        min_distance = float('inf')
                        for idx, table in enumerate(potential_tables):
                            distance = abs(text_item["y"] - table["y_start"])
                            if distance < min_distance:
                                min_distance = distance
                                closest_table_idx = idx
                        
                        if closest_table_idx is not None:
                            # Rename the table
                            old_name = f"table_{closest_table_idx + 1}"
                            new_name = known_table.lower()
                            if old_name in form_data["inspection_tables"]:
                                form_data["inspection_tables"][new_name] = form_data["inspection_tables"].pop(old_name)
            
            all_tables.append(form_data)
        
        return jsonify(all_tables), 200
        
    except Exception as e:
        import traceback
        return jsonify({
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
        
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
