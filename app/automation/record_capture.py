import base64
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

@dataclass
class RecordImage:
    mime_type: str
    natural_width: int
    natural_height: int
    image_bytes: bytes

@dataclass
class CaptureResult:
    created: bool
    output_path: Optional[Path] = None
    size_bytes: int = 0
    page_count: int = 0
    error_message: Optional[str] = None

class ImageCaptureError(Exception):
    pass

JS_EXTRACT_RECORD = """
() => {
    const img = document.querySelector('#ContentPlaceHolder1_ImgPC');
    if (!img) {
        return { error: 'Image element not found' };
    }
    
    const style = window.getComputedStyle(img);
    if (style.display === 'none' || style.visibility === 'hidden' || img.offsetWidth === 0) {
        return { error: 'Image element is not visible' };
    }
    
    if (img.naturalWidth === 0 || img.naturalHeight === 0) {
        return { error: 'Image natural dimensions are zero' };
    }
    
    if (!img.src) {
        return { error: 'Image src is empty' };
    }
    
    return {
        src: img.src,
        natural_width: img.naturalWidth,
        natural_height: img.naturalHeight
    };
}
"""

async def extract_record_image(page) -> RecordImage:
    """
    Extracts the original 7/12 record image from the Bhulekh DOM.
    Returns a RecordImage containing the decoded bytes and metadata.
    """
    result = await page.evaluate(JS_EXTRACT_RECORD)
    
    if "error" in result:
        raise ImageCaptureError(f"Extraction failed: {result['error']}")
        
    src = result["src"]
    
    if not src.startswith("data:image/"):
        raise ImageCaptureError("Unsupported image source type (not a data URL)")
        
    match = re.match(r"^data:(image/(?:jpeg|png));base64,(.+)$", src)
    if not match:
        raise ImageCaptureError("Invalid or unsupported data URL format (only base64 jpeg/png supported)")
        
    mime_type = match.group(1)
    base64_payload = match.group(2)
    
    try:
        image_bytes = base64.b64decode(base64_payload)
    except Exception as e:
        raise ImageCaptureError(f"Failed to decode base64 payload: {e}")
        
    if not image_bytes:
        raise ImageCaptureError("Decoded image bytes are empty")
        
    # Verify magic bytes/signatures
    if mime_type == "image/jpeg":
        if not image_bytes.startswith(b'\xff\xd8'):
            raise ImageCaptureError("Invalid JPEG signature")
    elif mime_type == "image/png":
        if not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ImageCaptureError("Invalid PNG signature")
            
    return RecordImage(
        mime_type=mime_type,
        natural_width=result["natural_width"],
        natural_height=result["natural_height"],
        image_bytes=image_bytes
    )

def save_record_pdf(record_image: RecordImage, output_path: Path) -> CaptureResult:
    """
    Converts the raw image bytes into a single-page PDF and saves it.
    Preserves original dimensions and quality as much as possible.
    """
    try:
        # Create output directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load image via Pillow
        with io.BytesIO(record_image.image_bytes) as img_io:
            with Image.open(img_io) as img:
                # Save as PDF
                # RGB mode is best for PDF saving in Pillow
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                    
                img.save(output_path, "PDF", resolution=100.0)
                
        # Validate output file
        if not output_path.exists():
            return CaptureResult(created=False, error_message="Failed to write PDF file (file does not exist after save)")
            
        file_size = output_path.stat().st_size
        if file_size == 0:
            return CaptureResult(created=False, error_message="Failed to write PDF file (file is empty)")
            
        return CaptureResult(
            created=True,
            output_path=output_path,
            size_bytes=file_size,
            page_count=1  # Always a single page since it's a single image
        )
    except Exception as e:
        return CaptureResult(created=False, error_message=f"PDF creation error: {str(e)}")
