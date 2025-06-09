@app.route('/api/split_pdf', methods=['POST'])
@auth.login_required
def split_pdf():
    import sys
    print("\n--- /api/split_pdf REQUEST RECEIVED ---", file=sys.stderr)
    print("Request.headers:", dict(request.headers), file=sys.stderr)
    print("Request.files keys:", list(request.files.keys()), file=sys.stderr)
    print("Request.form keys:", list(request.form.keys()), file=sys.stderr)
    print("--- END LOG ---\n", file=sys.stderr)

    # Try to get the PDF as a file, else fall back to raw form field
    file = request.files.get('pdf_file')
    if not file:
        # Try to get from form if n8n sent it as a string (base64 or raw)
        pdf_data = request.form.get('pdf_file')
        if pdf_data is None:
            return jsonify({"error": "No file part", "available_keys": list(request.files.keys())}), 400
        # pdf_data may be base64 or a raw PDF. Try both:
        try:
            # Try as base64
            import base64
            pdf_bytes = base64.b64decode(pdf_data, validate=True)
        except Exception:
            # Assume it's raw bytes
            pdf_bytes = pdf_data.encode('utf-8')
        file = io.BytesIO(pdf_bytes)
        file.filename = "upload.pdf"
        # Now use 'file' as a file-like object

    else:
        pdf_bytes = file.read()

    try:
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i in range(pdf.page_count):
                single_pdf = fitz.open()
                single_pdf.insert_pdf(pdf, from_page=i, to_page=i)
                pdf_bytes_io = io.BytesIO()
                single_pdf.save(pdf_bytes_io)
                single_pdf.close()
                pdf_bytes_io.seek(0)
                zipf.writestr(f"page_{i+1}.pdf", pdf_bytes_io.read())
        zip_buf.seek(0)
        return send_file(
            zip_buf,
            mimetype="application/zip",
            as_attachment=True,
            download_name="split_pages.zip"
        )
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500
