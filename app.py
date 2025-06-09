@app.route('/api/split_pdf', methods=['POST'])
@auth.login_required
def split_pdf():
    """
    Split the uploaded PDF into single-page PDFs, return as a ZIP.
    POST with 'pdf_file'.
    """

    # --- Begin Logging Block ---
    import sys
    print("\n--- /api/split_pdf REQUEST RECEIVED ---", file=sys.stderr)
    print("Request headers:", dict(request.headers), file=sys.stderr)
    print("Request.files keys:", list(request.files.keys()), file=sys.stderr)
    print("Request.form keys:", list(request.form.keys()), file=sys.stderr)
    print("Request.files object:", request.files, file=sys.stderr)
    print("Request.form object:", request.form, file=sys.stderr)
    # If files present, print their details
    for k, v in request.files.items():
        print(f"File key: {k}, filename: {v.filename}, content_type: {v.content_type}", file=sys.stderr)
    print("--- END LOG ---\n", file=sys.stderr)
    # --- End Logging Block ---

    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file part", "available_keys": list(request.files.keys())}), 400
    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        pdf = fitz.open(stream=file.read(), filetype="pdf")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i in range(pdf.page_count):
                single_pdf = fitz.open()
                single_pdf.insert_pdf(pdf, from_page=i, to_page=i)
                pdf_bytes = io.BytesIO()
                single_pdf.save(pdf_bytes)
                single_pdf.close()
                pdf_bytes.seek(0)
                zipf.writestr(f"page_{i+1}.pdf", pdf_bytes.read())
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
