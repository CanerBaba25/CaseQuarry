"""Fresh lossless raster PDFs: never copy source PDF objects into disclosures."""

import io
import math

from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from .pdf_runtime import PDFIUM_LOCK
from .security import fail

MAX_PAGES = 50
MAX_PIXELS = 40_000_000
SCALE = 2


def render_pdf(path, regions=(), page_number=None, information=None):
    import pypdfium2 as pdfium

    if any(flag.upper() in {"V8", "XFA"} for flag in pdfium.PDFIUM_INFO.flags):
        fail(503, "PDF_RUNTIME_UNSAFE", "Use a PDFium build without JavaScript or XFA support for protected rendering.")
    images, total_pixels = [], 0
    with PDFIUM_LOCK, pdfium.PdfDocument(str(path)) as document:
        count = len(document)
        if not 1 <= count <= MAX_PAGES:
            fail(413, "PRODUCTION_PAGE_LIMIT", "Flattened production supports 1 to 50 pages per document.")
        if any(region["page"] > count for region in regions):
            fail(422, "REDACTION_PAGE_INVALID", "A redaction refers to a page outside the source document.")
        if information is not None:
            information["page_count"] = count
        if page_number is not None and not 1 <= page_number <= count:
            fail(422, "REDACTION_PAGE_INVALID", "The selected preview page is outside the source document.")
        document.init_forms()
        for number in range(count) if page_number is None else [page_number - 1]:
            page = document[number]
            try:
                width, height = page.get_size()
                pixels = math.ceil(width * SCALE) * math.ceil(height * SCALE)
                total_pixels += pixels
                if pixels <= 0 or total_pixels > MAX_PIXELS:
                    fail(413, "PRODUCTION_PIXEL_LIMIT", "Rendered document exceeds the 40-million-pixel limit.")
                bitmap = page.render(scale=SCALE, draw_annots=True, may_draw_forms=True, fill_color=(255, 255, 255, 255))
                try:
                    image = bitmap.to_pil().convert("RGB").copy()
                finally:
                    bitmap.close()
                drawing = ImageDraw.Draw(image)
                for region in (value for value in regions if value["page"] == number + 1):
                    x, y, w, h = region["x"], region["y"], region["width"], region["height"]
                    box = (max(0, math.floor(x * image.width) - 2), max(0, math.floor(y * image.height) - 2), min(image.width - 1, math.ceil((x + w) * image.width) + 2), min(image.height - 1, math.ceil((y + h) * image.height) + 2))
                    drawing.rectangle(box, fill=(0, 0, 0))
                    if image.crop((box[0], box[1], box[2] + 1, box[3] + 1)).getextrema() != ((0, 0), (0, 0), (0, 0)):
                        fail(409, "REDACTION_VERIFICATION_FAILED", "The selected region was not fully burned into the pixels.")
                images.append(image)
            finally:
                page.close()
    return images


def clean_pdf(images):
    writer = PdfWriter()
    writer.metadata = None
    for image in images:
        image = image.convert("RGB")
        page = writer.add_blank_page(width=image.width / SCALE, height=image.height / SCALE)
        raw = DecodedStreamObject()
        raw.set_data(image.tobytes())
        stream = raw.flate_encode()
        stream.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"), NameObject("/Width"): NumberObject(image.width), NameObject("/Height"): NumberObject(image.height), NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/CQImage"): writer._add_object(stream)})})
        contents = DecodedStreamObject()
        contents.set_data(f"q {image.width / SCALE:g} 0 0 {image.height / SCALE:g} 0 0 cm /CQImage Do Q\n".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(contents)
    output = io.BytesIO()
    writer.write(output)
    data = output.getvalue()
    restored = clean_pdf_images(data)
    if len(restored) != len(images) or any(before.convert("RGB").tobytes() != after.tobytes() for before, after in zip(images, restored, strict=True)):
        fail(409, "REDACTION_VERIFICATION_FAILED", "Fresh PDF image streams failed lossless verification.")
    return data


def clean_pdf_images(data):
    reader = PdfReader(io.BytesIO(data), strict=True)
    root = reader.trailer["/Root"]
    if set(root) - {"/Type", "/Pages"} or reader.metadata or len(reader.pages) > MAX_PAGES:
        fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF contains unexpected document objects.")
    images, pixels = [], 0
    for page in reader.pages:
        if set(page) - {"/Type", "/Parent", "/Resources", "/MediaBox", "/Contents"} or page.extract_text():
            fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF contains hidden text or page objects.")
        resources = page["/Resources"]
        if set(resources) != {"/XObject"} or set(resources["/XObject"]) != {"/CQImage"}:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF has unexpected resources.")
        image = resources["/XObject"]["/CQImage"]
        if set(image) - {"/Type", "/Subtype", "/Width", "/Height", "/ColorSpace", "/BitsPerComponent", "/Filter"} or image["/ColorSpace"] != "/DeviceRGB" or image["/BitsPerComponent"] != 8:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF image format is invalid.")
        width, height = image["/Width"], image["/Height"]
        pixels += width * height
        if width <= 0 or height <= 0 or pixels > MAX_PIXELS + 10_000_000:
            fail(413, "PRODUCTION_PIXEL_LIMIT", "Flattened PDF image dimensions exceed the limit.")
        contents = page["/Contents"].get_data()
        expected = f"q {width / SCALE:g} 0 0 {height / SCALE:g} 0 0 cm /CQImage Do Q\n".encode("ascii")
        decoded = image.get_data()
        if contents != expected or len(decoded) != width * height * 3:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF has unexpected content streams.")
        images.append(Image.frombytes("RGB", (width, height), decoded))
    if not images:
        fail(409, "DERIVED_INTEGRITY_FAILED", "The flattened PDF has no verified pages.")
    return images


def stamped_images(images, labels):
    result = []
    for image, label in zip(images, labels, strict=True):
        # A new footer below the source avoids covering source content.
        footer = 60
        width = max(image.width, 360)
        canvas = Image.new("RGB", (width, image.height + footer), "white")
        canvas.paste(image, (0, 0))
        ImageDraw.Draw(canvas).text((16, image.height + 20), label, fill="black", font_size=22)
        result.append(canvas)
    return result
