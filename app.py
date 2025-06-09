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
