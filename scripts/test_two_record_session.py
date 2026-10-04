import asyncio
import json
import os
import sys
import time
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
INPUT_CAPTCHA = "#ContentPlaceHolder1_txtcaptcha"
IMG_CAPTCHA = "#ContentPlaceHolder1_imgCaptcha"
IMG_SELECTOR = "#ContentPlaceHolder1_ImgPC"
POPUP_SELECTOR = "#ContentPlaceHolder1_showPopUp"
BACK_SELECTOR = "#ContentPlaceHolder1_btnBack"

JS_GET_STATE = """
() => {
    const dist = document.querySelector('#ContentPlaceHolder1_ddlMainDist');
    const tal = document.querySelector('#ContentPlaceHolder1_ddlTalForAll');
    const vill = document.querySelector('#ContentPlaceHolder1_ddlVillForAll');
    const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
    const mobile = document.querySelector('#ContentPlaceHolder1_txtmobile1');
    const captcha_input = document.querySelector('#ContentPlaceHolder1_txtcaptcha');
    const captcha_img = document.querySelector('#ContentPlaceHolder1_imgCaptcha');
    
    const popup = document.querySelector('#ContentPlaceHolder1_showPopUp');
    const back_btn = document.querySelector('#ContentPlaceHolder1_btnBack');

    return {
        district_selected: (dist && dist.selectedIndex > 0),
        taluka_selected: (tal && tal.selectedIndex > 0),
        village_selected: (vill && vill.selectedIndex > 0),
        survey_selected: (survey && survey.selectedIndex >= 0),
        mobile_populated: (mobile && !!mobile.value),
        captcha_populated: (captcha_input && !!captcha_input.value),
        captcha_image_src: (captcha_img ? captcha_img.src : null),
        popup_visible: (popup && window.getComputedStyle(popup).display !== 'none'),
        back_btn_visible: (back_btn && window.getComputedStyle(back_btn).display !== 'none')
    };
}
"""

async def get_selected_survey_text(page) -> str:
    try:
        return await page.evaluate("""() => {
            const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
            if (survey && survey.selectedIndex >= 0) {
                return survey.options[survey.selectedIndex].text.trim();
            }
            return 'UNKNOWN';
        }""")
    except Exception:
        return "UNKNOWN"

async def capture_record(page, record_id: str, operator_action_msg: str):
    print("\n--------------------------------------------------")
    print(operator_action_msg)
    print("--------------------------------------------------")
    
    await asyncio.get_event_loop().run_in_executor(
        None, input, "Press ENTER here exactly WHEN you click Submit..."
    )
    
    t0 = time.time()
    
    print("\nWaiting for result image container to appear in DOM...")
    try:
        await page.wait_for_selector(IMG_SELECTOR, state="visible", timeout=60000)
        t1 = time.time()
        print(f"Result container is visible! (Wait time: {t1 - t0:.2f}s)")
    except Exception as e:
        print(f"Timeout waiting for {IMG_SELECTOR}: {e}")
        t1 = time.time()
        
    selected_survey = await get_selected_survey_text(page)
    
    ans = await asyncio.get_event_loop().run_in_executor(
        None, input, f"\nDoes the visible ImgPC image contain the correct {record_id} record? (y/n): "
    )
    is_visible = (ans.strip().lower() == "y")
    
    result_data = {
        "identifier": selected_survey,
        "success": is_visible,
        "submit_to_result_seconds": round(t1 - t0, 2),
        "capture_seconds": 0
    }
    
    if is_visible:
        print("\nExtracting original image bytes...")
        t2 = time.time()
        try:
            record_image = await extract_record_image(page)
            pdf_path = build_output_filepath(
                division="Pune", district="Pune", taluka="Maval", village="Shivali",
                survey_number=selected_survey, base_output_dir=OUTPUT_DIR, extension="pdf"
            )
            save_result = save_record_pdf(record_image, pdf_path)
            t3 = time.time()
            result_data["capture_seconds"] = round(t3 - t2, 2)
            
            print(f"PDF Capture Created: {save_result.created}")
            if save_result.created:
                print(f"Output Path: {save_result.output_path}")
        except Exception as e:
            print(f"Extraction failed: {e}")
            result_data["success"] = False
            
    return result_data

async def main():
    print("==================================================")
    print("PHASE: TWO-RECORD SEQUENTIAL SESSION & CAPTCHA TEST")
    print("==================================================")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # ---------------------------------------------------------
        # RECORD A
        # ---------------------------------------------------------
        print("\n--------------------------------------------------")
        print("RECORD A - INITIAL CAPTURE")
        print("1. Select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE simple numeric Survey/Gat Number (Record A).")
        print("3. Enter valid mobile number & manually enter CAPTCHA.")
        print("--------------------------------------------------")

        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip() and re.match(r"^[6-9]\d{9}$", TEST_MOBILE_NUMBER.strip()):
            try:
                if await page.locator(INPUT_MOBILE).is_visible():
                    await page.locator(INPUT_MOBILE).fill(TEST_MOBILE_NUMBER.strip())
            except Exception:
                pass
                
        initial_captcha_src = await page.evaluate("() => { const e = document.querySelector('#ContentPlaceHolder1_imgCaptcha'); return e ? e.src : null; }")

        record_a_result = await capture_record(page, "RECORD A", "ACTION: Complete form for Record A and CLICK SUBMIT")

        # ---------------------------------------------------------
        # STATE AFTER RECORD A
        # ---------------------------------------------------------
        print("\nChecking state IMMEDIATELY AFTER Record A...")
        state_after_a = await page.evaluate(JS_GET_STATE)
        state_after_a["captcha_changed"] = (state_after_a["captcha_image_src"] != initial_captcha_src)
        
        print(f"State After A: Popup Visible={state_after_a['popup_visible']}, Back Visible={state_after_a['back_btn_visible']}")

        # ---------------------------------------------------------
        # RETURN TO SEARCH (CLICK BACK)
        # ---------------------------------------------------------
        print("\n--------------------------------------------------")
        print("RETURN TO SEARCH")
        print("ACTION: Click the 'Back' (मागे) button on the site's result overlay.")
        print("--------------------------------------------------")
        
        await asyncio.get_event_loop().run_in_executor(
            None, input, "Press ENTER here AFTER you have clicked Back and the page has settled..."
        )
        
        print("\nChecking state AFTER BACK...")
        state_after_back = await page.evaluate(JS_GET_STATE)
        state_after_back["captcha_changed"] = (state_after_back["captcha_image_src"] != state_after_a["captcha_image_src"])
        
        print(f"State After Back: Location Preserved={state_after_back['district_selected'] and state_after_back['taluka_selected'] and state_after_back['village_selected']}")
        print(f"Survey Preserved={state_after_back['survey_selected']}, Mobile={state_after_back['mobile_populated']}, Captcha Input={state_after_back['captcha_populated']}")

        # ---------------------------------------------------------
        # RECORD B
        # ---------------------------------------------------------
        print("\n--------------------------------------------------")
        print("RECORD B - SECOND CAPTURE")
        print("1. Search & select a DIFFERENT numeric Survey/Gat Number (Record B).")
        print("2. Observe what the portal requires for CAPTCHA/Mobile.")
        print("--------------------------------------------------")
        
        await asyncio.get_event_loop().run_in_executor(
            None, input, "Press ENTER after selecting Record B and assessing what is required..."
        )
        
        ans_captcha = await asyncio.get_event_loop().run_in_executor(
            None, input, "\nDid the portal require you to enter a NEW CAPTCHA to submit Record B? (y/n): "
        )
        captcha_action = "CAPTCHA_REQUIRED_AGAIN" if ans_captcha.strip().lower() == 'y' else "CAPTCHA_REUSED_OR_SESSION_ACCEPTED"

        record_b_result = await capture_record(page, "RECORD B", "ACTION: Perform required actions (if any) and CLICK SUBMIT for Record B")
        record_b_result["captcha_action"] = captcha_action
        
        # ---------------------------------------------------------
        # CLASSIFICATION
        # ---------------------------------------------------------
        if captcha_action == "CAPTCHA_REQUIRED_AGAIN":
            classification = "CAPTCHA_REQUIRED_EACH_RECORD"
        elif captcha_action == "CAPTCHA_REUSED_OR_SESSION_ACCEPTED":
            classification = "CAPTCHA_REUSED_OR_SESSION_ACCEPTED"
        else:
            classification = "INCONCLUSIVE"
            
        if not state_after_back['district_selected']:
            classification = "LOCATION_RESET_AFTER_BACK"
            
        report = {
            "record_a": record_a_result,
            "after_record_a": {
                "location_preserved": (state_after_a['district_selected'] and state_after_a['taluka_selected'] and state_after_a['village_selected']),
                "survey_preserved": state_after_a['survey_selected'],
                "mobile_populated": state_after_a['mobile_populated'],
                "captcha_input_populated": state_after_a['captcha_populated'],
                "captcha_challenge_present": bool(state_after_a['captcha_image_src']),
                "captcha_changed": state_after_a['captcha_changed'],
                "popup_visible": state_after_a['popup_visible'],
                "back_visible": state_after_a['back_btn_visible']
            },
            "after_back": {
                "location_preserved": (state_after_back['district_selected'] and state_after_back['taluka_selected'] and state_after_back['village_selected']),
                "survey_preserved": state_after_back['survey_selected'],
                "mobile_populated": state_after_back['mobile_populated'],
                "captcha_input_populated": state_after_back['captcha_populated'],
                "captcha_challenge_present": bool(state_after_back['captcha_image_src']),
                "captcha_changed": state_after_back['captcha_changed']
            },
            "record_b": record_b_result,
            "classification": classification
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"two_record_session_{timestamp_str}.json"
        
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Technical two-record session report saved to: {report_file}")
        
        print("\nClosing browser...")
        await context.close()
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
