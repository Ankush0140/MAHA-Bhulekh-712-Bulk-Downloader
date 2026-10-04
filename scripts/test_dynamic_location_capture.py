import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.automation.location_reader import read_location_selection
from app.automation.record_capture import extract_record_image, save_record_pdf
from app.services.filename import build_output_filepath

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
IMG_SELECTOR = "#ContentPlaceHolder1_ImgPC"

async def main():
    print("==================================================")
    print("LIVE TEST: DYNAMIC LOCATION CAPTURE")
    print("==================================================")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("WORKFLOW (MANUAL SELECTION):")
        print("1. Please choose ANY location (Division, District, Taluka, Village) manually.")
        print("2. Search & select ONE available Survey/Gat Number.")
        print("3. Enter a valid mobile number.")
        print("4. Read and enter the CAPTCHA manually.")
        print("--------------------------------------------------")
        print("DO NOT CLICK SUBMIT YET!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nWhen form is fully complete (DO NOT CLICK SUBMIT), press ENTER here..."
        )

        try:
            print("\nReading actual selection from DOM...")
            location_selection, survey_identifier = await read_location_selection(page)
            
            print("\n--------------------------------------------------")
            print("ACTUAL PORTAL SELECTION:")
            print(f"District: {location_selection.district_text} (Value: {location_selection.district_value})")
            print(f"Taluka:   {location_selection.taluka_text} (Value: {location_selection.taluka_value})")
            print(f"Village:  {location_selection.village_text} (Value: {location_selection.village_value})")
            print(f"Survey:   {survey_identifier}")
            print("--------------------------------------------------")
            
            ans_proceed = await asyncio.get_event_loop().run_in_executor(
                None, input, "Proceed with this selection? (y/n): "
            )
            
            if ans_proceed.strip().lower() != 'y':
                print("Aborting.")
                await context.close()
                await browser.close()
                return

            print("\n--------------------------------------------------")
            print("ACTION: Click Submit in Chrome.")
            print("--------------------------------------------------")
            
            await asyncio.get_event_loop().run_in_executor(
                None, input, "Press ENTER here AFTER clicking Submit..."
            )

            print(f"Waiting for {IMG_SELECTOR} to become visible...")
            await page.wait_for_selector(IMG_SELECTOR, state="visible", timeout=60000)
            print("Result container is visible!")
            
            print("\nExtracting original image bytes...")
            record_image = await extract_record_image(page)
            
            pdf_path = build_output_filepath(
                location=location_selection,
                survey_number=survey_identifier,
                base_output_dir=OUTPUT_DIR,
                extension="pdf"
            )
            
            print(f"\nCreating clean PDF...")
            capture_result = save_record_pdf(record_image, pdf_path)
            
            if capture_result.created:
                print("\n==================================================")
                print("SUCCESS!")
                print(f"Actual Output Path: {capture_result.output_path}")
                print("==================================================")
                
                print("\nPlease manually verify the output.")
                ans_q1 = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Does the output District/Taluka/Village match exactly what you selected in Bhulekh? (y/n): "
                )
                ans_q2 = await asyncio.get_event_loop().run_in_executor(
                    None, input, "Does the PDF filename contain the correct selected Survey/Gat identifier in sanitized form? (y/n): "
                )
                
                if ans_q1.strip().lower() == 'y' and ans_q2.strip().lower() == 'y':
                    print("Dynamic location capture verified successfully.")
                else:
                    print("Verification failed based on operator feedback.")
            else:
                print(f"Failed to create PDF: {capture_result.error_message}")

        except Exception as e:
            print(f"\nError occurred: {e}")

        print("\nClosing browser...")
        await context.close()
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
