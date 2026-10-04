import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.config import TEST_MOBILE_NUMBER
import re

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"
IMG_SELECTOR = "#ContentPlaceHolder1_ImgPC"
POPUP_SELECTOR = "#ContentPlaceHolder1_showPopUp"
BACK_SELECTOR = "#ContentPlaceHolder1_btnBack"

JS_EXTRACT_IMG_INFO = """
() => {
    const img = document.querySelector('#ContentPlaceHolder1_ImgPC');
    if (!img) return { exists: false, visible: false };
    
    const style = window.getComputedStyle(img);
    const visible = style.display !== 'none' && style.visibility !== 'hidden' && img.offsetWidth > 0;
    
    let src_type = "empty/other";
    let mime_type = null;
    let encoded_length = 0;
    let origin = null;
    let path = null;
    
    const src = img.src || "";
    
    if (src.startsWith('data:')) {
        src_type = "data";
        const match = src.match(/^data:([^;]+);/);
        if (match) {
            mime_type = match[1];
        }
        encoded_length = src.length;
    } else if (src.startsWith('blob:')) {
        src_type = "blob";
        // Blob type/length cannot be easily extracted purely from the URL synchronously without fetching it.
    } else if (src.startsWith('http://') || src.startsWith('https://')) {
        src_type = "http/https";
        try {
            const url = new URL(src);
            origin = url.origin;
            path = url.pathname;
        } catch(e) {}
    } else if (src.length > 0) {
        src_type = "relative";
        path = src.split('?')[0]; // sanitize params
    }
    
    return {
        exists: true,
        visible: visible,
        natural_width: img.naturalWidth,
        natural_height: img.naturalHeight,
        rendered_width: img.getBoundingClientRect().width,
        rendered_height: img.getBoundingClientRect().height,
        src_type: src_type,
        mime_type: mime_type,
        encoded_length: encoded_length,
        origin: origin,
        path: path
    };
}
"""

JS_EXTRACT_STRUCTURE = """
() => {
    const popup = document.querySelector('#ContentPlaceHolder1_showPopUp');
    const img = document.querySelector('#ContentPlaceHolder1_ImgPC');
    const back = document.querySelector('#ContentPlaceHolder1_btnBack');
    
    let img_inside = false;
    let back_inside = false;
    
    if (popup) {
        if (img && popup.contains(img)) img_inside = true;
        if (back && popup.contains(back)) back_inside = true;
        
        return {
            popup_exists: true,
            inside_show_popup: img_inside,
            back_inside_show_popup: back_inside,
            num_img_descendants: popup.querySelectorAll('img').length,
            num_table_descendants: popup.querySelectorAll('table').length,
            num_input_button_descendants: popup.querySelectorAll('input, button').length
        };
    }
    
    return { popup_exists: false };
}
"""

async def main():
    print("==================================================")
    print("PHASE: RESULT IMAGE DELIVERY INSPECTION")
    print("==================================================")
    
    network_logs = []
    
    async def handle_response(response):
        # We only care about images during the post-submit window.
        # But we'll collect all image types just in case.
        try:
            content_type = response.headers.get('content-type', '').lower()
            if 'image/' in content_type:
                parsed_url = urlparse(response.url)
                # Avoid logging full URL query strings.
                network_logs.append({
                    "method": response.request.method,
                    "origin": f"{parsed_url.scheme}://{parsed_url.netloc}",
                    "path": parsed_url.path,
                    "status": response.status,
                    "content_type": content_type,
                    "content_length": response.headers.get('content-length')
                })
        except Exception:
            pass

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()
        page.on("response", handle_response)

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip() and re.match(r"^[6-9]\d{9}$", TEST_MOBILE_NUMBER.strip()):
            print(f"\n[CONFIG] Operator test mobile number configured: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("WORKFLOW:")
        print("1. Select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE simple numeric Survey/Gat Number.")
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip() and re.match(r"^[6-9]\d{9}$", TEST_MOBILE_NUMBER.strip()):
            print(f"3. Mobile number will autofill into field...")
            try:
                if await page.locator(INPUT_MOBILE).is_visible():
                    await page.locator(INPUT_MOBILE).fill(TEST_MOBILE_NUMBER.strip())
            except Exception:
                pass
        else:
            print("3. Enter a valid 10-digit Indian mobile number starting with 6-9.")
        print("4. Read and enter CAPTCHA manually into the CAPTCHA field.")
        print("--------------------------------------------------")
        print("DO NOT CLICK SUBMIT YET!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nWhen form is complete (DO NOT CLICK SUBMIT), press ENTER here to establish pre-submit boundary..."
        )

        # Clear network logs to only capture post-submit images
        network_logs.clear()
        
        print("\n--------------------------------------------------")
        print("ACTION FOR OPERATOR:")
        print("1. Click Submit ONCE in Google Chrome.")
        print(f"2. Wait for {IMG_SELECTOR} to become visible.")
        print("--------------------------------------------------")

        print("Waiting for result image container to appear in the DOM...")
        try:
            await page.wait_for_selector(IMG_SELECTOR, state="visible", timeout=60000)
            print("Result container became visible!")
        except Exception as e:
            print(f"Timeout or error waiting for {IMG_SELECTOR}: {e}")
            await asyncio.get_event_loop().run_in_executor(
                None, input, "Press ENTER to continue anyway..."
            )

        print("\nExtracting ImgPC technical metadata...")
        img_info = await page.evaluate(JS_EXTRACT_IMG_INFO)
        structure_info = await page.evaluate(JS_EXTRACT_STRUCTURE)
        
        # Display safe info
        print(f"\n#ContentPlaceHolder1_ImgPC Info:")
        print(json.dumps(img_info, indent=2))
        
        print(f"\nStructure Info:")
        print(json.dumps(structure_info, indent=2))
        
        ans = await asyncio.get_event_loop().run_in_executor(
            None, input, "\nDoes the visible ImgPC image contain the entire 7/12 record? (y/n): "
        )
        is_complete = (ans.strip().lower() == "y")
        
        strategy = "UNKNOWN"
        if is_complete and img_info.get("src_type") in ("data", "blob", "http/https", "relative"):
            strategy = "DIRECT_IMAGE_BYTES"
        elif is_complete:
            strategy = "RESULT_ELEMENT_SCREENSHOT"
        else:
            strategy = "PRINT_RESULT_CONTAINER"
            
        print(f"\nRecommended capture strategy: {strategy}")
        
        report = {
            "imgpc": img_info,
            "structure": structure_info,
            "network_images": network_logs,
            "operator_confirmed_complete_record_image": is_complete,
            "recommended_capture_strategy": strategy
        }
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"image_inspection_{timestamp_str}.json"
        
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        print(f"\n[SAVED] Technical image metadata saved to: {report_file}")
        
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
