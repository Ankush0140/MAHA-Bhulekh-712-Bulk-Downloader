import base64
import os
import pytest
from pathlib import Path
from PIL import Image
import io

from app.automation.record_capture import (
    extract_record_image,
    save_record_pdf,
    RecordImage,
    ImageCaptureError,
    CaptureResult
)
from app.services.filename import sanitize_filename_component

# Synthetic Jpeg bytes (1x1 pixel)
SYNTHETIC_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x00\xff\xd9"
SYNTHETIC_JPEG_B64 = base64.b64encode(SYNTHETIC_JPEG).decode("ascii")

# Synthetic PNG bytes (1x1 pixel)
SYNTHETIC_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
SYNTHETIC_PNG_B64 = base64.b64encode(SYNTHETIC_PNG).decode("ascii")

class MockPage:
    def __init__(self, result):
        self.result = result

    async def evaluate(self, script):
        return self.result


@pytest.mark.asyncio
async def test_valid_jpeg_data_url_decoding():
    page = MockPage({
        "src": f"data:image/jpeg;base64,{SYNTHETIC_JPEG_B64}",
        "natural_width": 1,
        "natural_height": 1
    })
    
    record = await extract_record_image(page)
    assert record.mime_type == "image/jpeg"
    assert record.natural_width == 1
    assert record.natural_height == 1
    assert record.image_bytes == SYNTHETIC_JPEG

@pytest.mark.asyncio
async def test_valid_png_data_url_decoding():
    page = MockPage({
        "src": f"data:image/png;base64,{SYNTHETIC_PNG_B64}",
        "natural_width": 1,
        "natural_height": 1
    })
    
    record = await extract_record_image(page)
    assert record.mime_type == "image/png"
    assert record.image_bytes == SYNTHETIC_PNG

@pytest.mark.asyncio
async def test_unsupported_mime_rejected():
    page = MockPage({
        "src": f"data:image/gif;base64,R0lGOD...",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Invalid or unsupported data URL format"):
        await extract_record_image(page)

@pytest.mark.asyncio
async def test_malformed_data_url_rejected():
    page = MockPage({
        "src": "data:image/jpegbase64,123",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Invalid or unsupported data URL format"):
        await extract_record_image(page)

@pytest.mark.asyncio
async def test_invalid_base64_rejected():
    page = MockPage({
        "src": "data:image/jpeg;base64,@@@@invalid@@@@",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Failed to decode base64 payload"):
        await extract_record_image(page)

@pytest.mark.asyncio
async def test_empty_image_rejected():
    page = MockPage({
        "src": "data:image/jpeg;base64,",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Invalid or unsupported data URL format"):
        await extract_record_image(page)

@pytest.mark.asyncio
async def test_jpeg_signature_validation():
    # Valid base64 but missing jpeg magic bytes
    bad_bytes = b"bad_jpeg_data"
    bad_b64 = base64.b64encode(bad_bytes).decode('ascii')
    
    page = MockPage({
        "src": f"data:image/jpeg;base64,{bad_b64}",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Invalid JPEG signature"):
        await extract_record_image(page)

@pytest.mark.asyncio
async def test_png_signature_validation():
    bad_bytes = b"bad_png_data"
    bad_b64 = base64.b64encode(bad_bytes).decode('ascii')
    
    page = MockPage({
        "src": f"data:image/png;base64,{bad_b64}",
        "natural_width": 1,
        "natural_height": 1
    })
    
    with pytest.raises(ImageCaptureError, match="Invalid PNG signature"):
        await extract_record_image(page)

def test_image_to_pdf_output_exists_and_non_empty(tmp_path):
    record = RecordImage(
        mime_type="image/jpeg",
        natural_width=1,
        natural_height=1,
        image_bytes=SYNTHETIC_JPEG
    )
    
    out_pdf = tmp_path / "test_record.pdf"
    result = save_record_pdf(record, out_pdf)
    
    assert result.created is True
    assert result.output_path == out_pdf
    assert result.size_bytes > 0
    assert result.page_count == 1
    assert out_pdf.exists()

def test_pdf_signature_valid(tmp_path):
    record = RecordImage(
        mime_type="image/jpeg",
        natural_width=1,
        natural_height=1,
        image_bytes=SYNTHETIC_JPEG
    )
    
    out_pdf = tmp_path / "test_signature.pdf"
    save_record_pdf(record, out_pdf)
    
    with open(out_pdf, "rb") as f:
        pdf_bytes = f.read(5)
    
    # PDF files start with %PDF-
    assert pdf_bytes == b"%PDF-"

def test_filename_sanitization():
    # slash identifier sanitization
    assert sanitize_filename_component("115/1/A") == "115-1-A"
    
    # Devanagari identifier handling
    assert sanitize_filename_component("17/10/ए") == "17-10-ए"
    assert sanitize_filename_component("17/11/बी") == "17-11-बी"
    
    # Windows-safe filename
    assert sanitize_filename_component('bad<">name?*|\\') == "bad-name"
