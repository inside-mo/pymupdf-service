@app.route('/api/extract-text', methods=['POST'])
@auth.login_required
def extract_text():
    # ... [previous error checking code remains the same]
    try:
        pdf_data = file.read()
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        
        # Change to page-ordered dictionary
        result = {str(page_num): {} for page_num in range(len(doc))}
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            result[str(page_num)] = {}  # Initialize page container
            # [Rest of existing extraction logic, but store in result[str(page_num)]]
            
        return jsonify(result)

@app.route('/api/get-checkboxes', methods=['POST'])
@auth.login_required
def get_checkboxes():
    # ... [previous error checking code remains the same]
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        checkbox_content = {str(i): [] for i in range(len(doc))}  # Page-organized dict
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            fields = page.widgets()
            
            for field in fields:
                if field.field_type == fitz.PDF_WIDGET_TYPE_CHECKBOX:
                    rect = field.rect
                    checkbox_content[str(page_num)].append({
                        'name': field.field_name,
                        'value': field.field_value,
                        'y_pos': rect.y0,
                        'x_pos': rect.x0
                    })
            
            # Sort by position within each page
            checkbox_content[str(page_num)].sort(key=lambda x: (x['y_pos'], x['x_pos']))
        
        return jsonify(checkbox_content)

@app.route('/api/extract-all-fields', methods=['POST'])
@auth.login_required
def extract_all_fields():
    # ... [previous error checking code remains the same]
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
        results = {str(i): {} for i in range(len(doc))}  # Page-organized dict
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            blocks = page.get_text("dict")["blocks"]
            
            # [Previous extraction logic, but store in results[str(page_num)]]
            
        return jsonify(results)
