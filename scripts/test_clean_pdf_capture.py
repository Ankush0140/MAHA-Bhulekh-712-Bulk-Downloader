import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.automation.pdf_capture import save_rendered_record_as_pdf
from app.services.filename import build_output_filepath
from app.config import TEST_MOBILE_NUMBER

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"


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
    print("MAHA Bhulekh Clean Record-Only PDF Capture Test")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Autofill test mobile if configured
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip() and re.match(r"^[6-9]\d{9}$", TEST_MOBILE_NUMBER.strip()):
            print(f"\n[CONFIG] Operator test mobile number configured: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
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
            None, input, "\nWhen form, mobile & CAPTCHA are complete (DO NOT CLICK SUBMIT YET), press ENTER here..."
        )

        selected_survey = await get_selected_survey_text(page)
        print(f"\nCaptured Selected Survey Record: '{selected_survey}'")

        print("\n--------------------------------------------------")
        print("ACTION FOR OPERATOR:")
        print("1. Click Submit ONCE in Google Chrome.")
        print("2. Wait until the requested 7/12 extract is fully rendered on the page.")
        print("3. Press ENTER in this terminal.")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter clicking Submit and verifying the 7/12 is visibly rendered in Chrome, press ENTER here..."
        )

        ans = await asyncio.get_event_loop().run_in_executor(
            None, input, "\nIs the correct 7/12 extract visibly rendered on the page right now? (y/n): "
        )
        is_visible = (ans.strip().lower() == "y")

        pdf_result_data = {}

        if is_visible:
            # Build target output filepath: output/Pune/Maval/Shivali/Pune_Maval_Shivali_1.pdf (no duplicated Pune/Pune)
            pdf_path = build_output_filepath(
                division="Pune",
                district="Pune",
                taluka="Maval",
                village="Shivali",
                survey_number=selected_survey,
                base_output_dir=OUTPUT_DIR,
                extension="pdf"
            )

            print(f"\nExecuting DOM-based clean PDF capture (hiding search form & clutter)...")
            pdf_capture_res = await save_rendered_record_as_pdf(
                page,
                output_path=pdf_path,
                target_container_selector=None,  # Auto-detects 7/12 result container
                print_background=True,
                prefer_css_page_size=True
            )

            print("\n--------------------------------------------------")
            print("CLEAN PDF TECHNICAL VALIDATION SUMMARY:")
            print("--------------------------------------------------")
            print(f"PDF File Created?      {pdf_capture_res.created}")
            print(f"Saved Output Path:      {pdf_capture_res.output_path}")
            print(f"File Size:              {pdf_capture_res.size_bytes} bytes")
            print(f"Estimated Page Count:   {pdf_capture_res.page_count}")
            if pdf_capture_res.error_message:
                print(f"Error Message:         {pdf_capture_res.error_message}")

            # Operator visual validation
            print("\n--------------------------------------------------")
            print(f"MANUAL VISUAL VALIDATION REQUIRED:")
            print(f"Please open the generated PDF file manually at:")
            print(f"  {pdf_capture_res.output_path}")
            print("--------------------------------------------------")

            q1_ans = await asyncio.get_event_loop().run_in_executor(
                None, input, "Q1: Does the PDF contain ONLY the 7/12 record without the Bhulekh search form, mobile field, CAPTCHA or footer clutter? (y/n): "
            )
            only_record_clean = (q1_ans.strip().lower() == "y")

            q2_ans = await asyncio.get_event_loop().run_in_executor(
                None, input, "Q2: Is the entire 7/12 readable and unclipped? (y/n): "
            )
            readable = (q2_ans.strip().lower() == "y")

            pdf_result_data = {
                "created": pdf_capture_res.created,
                "output_path": pdf_capture_res.output_path,
                "size_bytes": pdf_capture_res.size_bytes,
                "page_count": pdf_capture_res.page_count,
                "operator_confirmed_only_record_clean": only_record_clean,
                "operator_confirmed_readable": readable
            }
        else:
            print("\nOperator answered 'n'. Skipping PDF capture.")
            pdf_result_data = {"created": False, "reason": "Operator indicated 7/12 was not rendered."}

        # Save technical JSON
        report = {
            "timestamp": datetime.now().isoformat(),
            "selected_survey": selected_survey,
            "operator_confirmed_result_visible": is_visible,
            "pdf_result": pdf_result_data
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"clean_pdf_capture_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Technical clean PDF capture report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
