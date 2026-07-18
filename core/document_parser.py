from io import BytesIO


def extract_pdf_text(pdf_bytes, max_chars=30000):
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("缺少 pypdf 依赖，请先安装 requirements.txt") from e

    reader = PdfReader(BytesIO(pdf_bytes))
    parts = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            parts.append(f"[PDF Page {index}]\n{text.strip()}")

    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError("PDF 未提取到文本，可能是扫描件，请先 OCR 或使用视觉模型解析。")
    return content[:max_chars]


def render_pdf_pages(pdf_bytes, max_pages=3, zoom=1.5):
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError("缺少 PyMuPDF 依赖，请先安装 requirements.txt") from e

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    matrix = fitz.Matrix(zoom, zoom)
    for page_index in range(min(max_pages, len(doc))):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        images.append({
            "page": page_index + 1,
            "mime_type": "image/png",
            "data": pix.tobytes("png"),
        })
    doc.close()
    return images
