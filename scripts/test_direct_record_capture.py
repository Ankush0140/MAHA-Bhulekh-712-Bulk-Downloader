import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.automation.record_capture import extract_record_image, save_record_pdf
from app.services.filename import build_output_filepath
from app.config import TEST_MOBILE_NUMBER
import re

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"
IMG_SELECTOR = "#ContentPlaceHolder1_ImgPC"

async def get_selected_survey_text(page) -> str:
    """Retrieve text of currently selected survey option."""
    try:
        return await page.evaluate("""() => {
            const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
            if (survey && survey.selectedIndex >= 0) {
                return survey.options[survey.selectedIndex].text.trim();
            }
            return '1';
        }""")
    except Exception:
        return "1"

async def main():
    print("==================================================")
    print("LIVE TEST: DIRECT RECORD CAPTURE (IMAGE TO PDF)")
    print("==================================================")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

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
        print("ACTION: CLICK SUBMIT!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, f"\nAfter clicking Submit and waiting for {IMG_SELECTOR} to become visible, press ENTER here..."
        )

        print("\nWaiting to ensure result image container is available in DOM...")
        try:
            await page.wait_for_selector(IMG_SELECTOR, state="visible", timeout=15000)
            print("Result container is visible!")
        except Exception as e:
            print(f"Timeout or error waiting for {IMG_SELECTOR}: {e}")

        selected_survey = await get_selected_survey_text(page)

        ans = await asyncio.get_event_loop().run_in_executor(
            None, input, "\nDoes the visible ImgPC image contain the correct 7/12 record? (y/n): "
        )
        is_visible = (ans.strip().lower() == "y")

        pdf_result_data = {}
        source_data = {}
        
        if is_visible:
            print("\nExtracting original image bytes...")
            try:
                record_image = await extract_record_image(page)
                
                source_data = {
                    "mime": record_image.mime_type,
                    "natural_width": record_image.natural_width,
                    "natural_height": record_image.natural_height,
                    "decoded_size_bytes": len(record_image.image_bytes)
                }
                
                print("Source Image Metadata:")
                print(f"  Survey Identifier: {selected_survey}")
                print(f"  Source MIME:       {record_image.mime_type}")
                print(f"  Natural Dims:      {record_image.natural_width} x {record_image.natural_height}")
                print(f"  Decoded Size:      {len(record_image.image_bytes)} bytes")
                
                pdf_path = build_output_filepath(
                    division="Pune",
                    district="Pune",
                    taluka="Maval",
                    village="Shivali",
                    survey_number=selected_survey,
                    base_output_dir=OUTPUT_DIR,
                    extension="pdf"
                )
                
                print(f"\nCreating clean PDF...")
                capture_result = save_record_pdf(record_image, pdf_path)
                
                print("PDF Capture Result:")
                print(f"  Created?     {capture_result.created}")
                if capture_result.created:
                    print(f"  Output Path: {capture_result.output_path}")
                    print(f"  File Size:   {capture_result.size_bytes} bytes")
                    print(f"  Page Count:  {capture_result.page_count}")
                else:
                    print(f"  Error:       {capture_result.error_message}")
                
                if capture_result.created:
                    print("\n--------------------------------------------------")
                    print("MANUAL VISUAL VALIDATION REQUIRED")
                    print(f"Please open the generated PDF file manually at:")
                    print(f"  {capture_result.output_path}")
                    print("--------------------------------------------------")
                    
                    q1_ans = await asyncio.get_event_loop().run_in_executor(
                        None, input, "Does the PDF contain ONLY the complete 7/12 and no surrounding Bhulekh webpage? (y/n): "
                    )
                    only_record_clean = (q1_ans.strip().lower() == "y")
        
                    q2_ans = await asyncio.get_event_loop().run_in_executor(
                        None, input, "Is it sharp, readable and unclipped? (y/n): "
                    )
                    readable = (q2_ans.strip().lower() == "y")
                    
                    pdf_result_data = {
                        "created": True,
                        "size_bytes": capture_result.size_bytes,
                        "page_count": capture_result.page_count,
                        "operator_confirmed_clean": only_record_clean,
                        "operator_confirmed_readable": readable
                    }
                else:
                    pdf_result_data = {"created": False, "error": capture_result.error_message}

            except Exception as e:
                print(f"\nExtraction failed: {e}")
                pdf_result_data = {"created": False, "error": str(e)}
        else:
            print("\nOperator indicated 7/12 was not rendered.")
            pdf_result_data = {"created": False, "reason": "Operator indicated 7/12 was not rendered."}

        report = {
            "survey_identifier": selected_survey,
            "source": source_data,
            "pdf": pdf_result_data
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"direct_record_capture_{timestamp_str}.json"
        
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Technical PDF capture report saved to: {report_file}")
        
        print("\nClosing browser...")
        await context.close()
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
