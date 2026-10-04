import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, Response, Download

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.config import TEST_MOBILE_NUMBER

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Selectors
SELECT_DISTRICT = "#ContentPlaceHolder1_ddlMainDist"
SELECT_TALUKA = "#ContentPlaceHolder1_ddlTalForAll"
SELECT_VILLAGE = "#ContentPlaceHolder1_ddlVillForAll"
SELECT_SURVEY = "#ContentPlaceHolder1_ddlsurveyno"
INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"
INPUT_CAPTCHA = "#ContentPlaceHolder1_txtcaptcha"
BTN_SUBMIT = "#ContentPlaceHolder1_btnmainsubmit"

# Post-submit event buffers
post_submit_events = {
    "popups": [],
    "downloads": [],
    "responses": []
}


async def inspect_boundary_state(page: Page) -> dict:
    """Inspect form state at pre-submit boundary (booleans and safe metadata ONLY)."""
    return await page.evaluate("""() => {
        const dist = document.querySelector('#ContentPlaceHolder1_ddlMainDist');
        const tal = document.querySelector('#ContentPlaceHolder1_ddlTalForAll');
        const vill = document.querySelector('#ContentPlaceHolder1_ddlVillForAll');
        const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
        const mobile = document.querySelector('#ContentPlaceHolder1_txtmobile1') || document.querySelector('input[id*="mobile"]');
        const captcha = document.querySelector('#ContentPlaceHolder1_txtcaptcha') || document.querySelector('input[id*="captcha"]');
        const btn = document.querySelector('#ContentPlaceHolder1_btnmainsubmit') || document.querySelector('input[type="submit"]');

        const mobileVal = mobile ? (mobile.value || '').trim() : '';
        const captchaVal = captcha ? (captcha.value || '').trim() : '';
        const validMobileShape = /^\\d{10}$/.test(mobileVal) && /^[6-9]/.test(mobileVal);

        return {
            districtSelected: dist ? (dist.selectedIndex > 0) : false,
            talukaSelected: tal ? (tal.selectedIndex > 0) : false,
            villageSelected: vill ? (vill.selectedIndex > 0) : false,
            surveySelected: survey ? (survey.selectedIndex > 0 && survey.value !== '0' && survey.value !== '') : false,
            surveySelectedText: survey && survey.selectedIndex >= 0 ? survey.options[survey.selectedIndex].text : null,
            mobilePopulated: mobileVal.length > 0,
            mobileLength: mobileVal.length,
            mobileValidFormat: validMobileShape,
            captchaPopulated: captchaVal.length > 0,
            submitVisible: btn ? (btn.offsetWidth > 0 && btn.offsetHeight > 0) : false,
            submitEnabled: btn ? !btn.disabled : false
        };
    }""")


async def inspect_post_submit_delivery(main_page: Page, popup_pages: list[Page]) -> dict:
    """Analyze technical delivery mechanism of the rendering page/popup."""
    pages_to_check = [main_page] + popup_pages
    
    delivery = {
        "same_page_url_changed": False,
        "popup_after_submit": len(popup_pages) > 0,
        "popup_count": len(popup_pages),
        "download_event_triggered": len(post_submit_events["downloads"]) > 0,
        "download_info": post_submit_events["downloads"],
        "responses_summary": post_submit_events["responses"],
        "main_page_final_url": main_page.url.split("?")[0],
        "popup_urls": [pg.url.split("?")[0] for pg in popup_pages],
        "iframe_count": 0,
        "iframe_sources": [],
        "embed_object_present": False,
        "pdf_viewer_detected": False,
        "html_document": False,
        "image_document": False,
        "print_control_present": False,
        "page_titles": []
    }

    for idx, pg in enumerate(pages_to_check):
        try:
            title = await pg.title()
            delivery["page_titles"].append(title)

            analysis = await pg.evaluate("""() => {
                const iframes = Array.from(document.querySelectorAll('iframe, frame')).map(f => f.src ? f.src.split('?')[0] : 'about:blank');
                const embeds = document.querySelectorAll('embed, object');
                const pdfs = document.querySelectorAll('embed[type*="pdf"], object[type*="pdf"], iframe[src*=".pdf"]');
                const imgs = document.querySelectorAll('img');

                const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
                const hasPrintText = bodyText.includes('print') || bodyText.includes('छापा') || bodyText.includes('मुद्रण');
                const hasPrintBtn = Array.from(document.querySelectorAll('button, input[type="button"], a')).some(
                    el => (el.innerText || el.value || '').toLowerCase().includes('print') || (el.innerText || el.value || '').includes('छापा')
                );

                return {
                    iframeCount: iframes.length,
                    iframeSources: iframes,
                    embedCount: embeds.length,
                    pdfViewerCount: pdfs.length,
                    imageCount: imgs.length,
                    isHtml: document.contentType ? document.contentType.includes('html') : true,
                    hasPrintControl: hasPrintText || hasPrintBtn
                };
            }""")

            delivery["iframe_count"] += analysis["iframeCount"]
            delivery["iframe_sources"].extend(analysis["iframeSources"])
            if analysis["embedCount"] > 0:
                delivery["embed_object_present"] = True
            if analysis["pdfViewerCount"] > 0:
                delivery["pdf_viewer_detected"] = True
            if analysis["isHtml"]:
                delivery["html_document"] = True
            if analysis["hasPrintControl"]:
                delivery["print_control_present"] = True

        except Exception as e:
            print(f"[INSPECT WARNING] Could not analyze page {idx}: {e}")

    return delivery


async def inspect_post_submit_session(main_page: Page) -> dict:
    """Check if main Bhulekh form retains location and survey selection after submit."""
    try:
        return await main_page.evaluate("""() => {
            const dist = document.querySelector('#ContentPlaceHolder1_ddlMainDist');
            const tal = document.querySelector('#ContentPlaceHolder1_ddlTalForAll');
            const vill = document.querySelector('#ContentPlaceHolder1_ddlVillForAll');
            const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
            const captchaImg = document.querySelector('#ContentPlaceHolder1_imgCaptcha') || document.querySelector('img[id*="Captcha"]');

            return {
                original_page_available: true,
                district_preserved: dist ? (dist.selectedIndex > 0) : false,
                taluka_preserved: tal ? (tal.selectedIndex > 0) : false,
                village_preserved: vill ? (vill.selectedIndex > 0) : false,
                survey_preserved: survey ? (survey.selectedIndex > 0) : false,
                captcha_reset: captchaImg ? true : false
            };
        }""")
    except Exception as e:
        print(f"[SESSION INSPECTION WARNING] Error checking session persistence: {e}")
        return {"original_page_available": False, "error": str(e)}


async def main():
    print("==================================================")
    print("MAHA Bhulekh Successful Single-Record Delivery Inspector")
    print("==================================================")
    print("Launching Google Chrome...")

    popup_pages_after_submit = []

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Autofill test mobile number if configured
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"\n[CONFIG] Operator test mobile number configured: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
        print("1. Select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE simple numeric Survey/Gat Number.")
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip() and re.match(r"^[6-9]\d{9}$", TEST_MOBILE_NUMBER.strip()):
            print(f"3. Autofilling mobile number into field...")
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

        # STEP 1: PRE-SUBMIT BOUNDARY CHECK
        print("\n1. Capturing Pre-Submit Boundary State...")
        pre_state = await inspect_boundary_state(page)

        print("\n--- PRE-SUBMIT BOUNDARY CHECK ---")
        print(f"District Selected?      {pre_state['districtSelected']}")
        print(f"Taluka Selected?        {pre_state['talukaSelected']}")
        print(f"Village Selected?       {pre_state['villageSelected']}")
        print(f"Survey Selected?        {pre_state['surveySelected']} ('{pre_state.get('surveySelectedText')}')")
        print(f"Mobile Field Populated: {pre_state['mobilePopulated']} (Length: {pre_state['mobileLength']})  [BOOLEAN ONLY]")
        print(f"Mobile Valid Format?    {pre_state['mobileValidFormat']}")
        print(f"CAPTCHA Field Populated: {pre_state['captchaPopulated']}  [BOOLEAN ONLY]")
        print(f"Submit Button Ready?    {pre_state['submitVisible'] and pre_state['submitEnabled']}")

        pre_url = page.url
        pre_title = await page.title()

        # STEP 2: ACTIVATE POST-SUBMIT LISTENERS ONLY AFTER ENTER
        print("\n2. Resetting buffers & activating POST-SUBMIT event listeners...")

        def on_post_submit_popup(new_pg: Page):
            popup_pages_after_submit.append(new_pg)
            print(f"\n[POST-SUBMIT EVENT] New Popup/Tab Opened! Base URL: {new_pg.url.split('?')[0]}")

        def on_post_submit_download(dload: Download):
            post_submit_events["downloads"].append({
                "timestamp": datetime.now().isoformat(),
                "suggested_filename": dload.suggested_filename,
                "url_base": dload.url.split("?")[0]
            })
            print(f"\n[POST-SUBMIT EVENT] Native Download Triggered! Filename: {dload.suggested_filename}")

        def on_post_submit_response(resp: Response):
            try:
                url = resp.url
                if "mahabhumi.gov.in" in url:
                    ct = resp.headers.get("content-type", "")
                    post_submit_events["responses"].append({
                        "timestamp": datetime.now().isoformat(),
                        "method": resp.request.method,
                        "status": resp.status,
                        "content_type": ct,
                        "url_base": url.split("?")[0]
                    })
                    print(f"[POST-SUBMIT NETWORK] {resp.request.method} HTTP {resp.status} {url.split('?')[0]} ({ct})")
            except Exception:
                pass

        context.on("page", on_post_submit_popup)
        page.on("download", on_post_submit_download)
        page.on("response", on_post_submit_response)

        print("\n--------------------------------------------------")
        print("ACTION FOR OPERATOR:")
        print("1. Click Submit ONCE in Google Chrome.")
        print("2. Wait until the 7/12 extract is fully visible in Chrome.")
        print("3. Press ENTER in this terminal.")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter clicking Submit and verifying the 7/12 is visibly rendered/opened, press ENTER here..."
        )

        # Confirm operator observation
        ans = await asyncio.get_event_loop().run_in_executor(
            None, input, "\nIs the requested 7/12 record visibly rendered/opened in Chrome right now? (y/n): "
        )
        operator_confirmed = (ans.strip().lower() == 'y')

        # STEP 3: ANALYZE TECHNICAL DELIVERY & SESSION PERSISTENCE
        print("\n3. Analyzing Technical Delivery Mechanism & Session Persistence...")
        delivery = await inspect_post_submit_delivery(page, popup_pages_after_submit)
        session_info = await inspect_post_submit_session(page)

        print("\n==================================================")
        print("SUCCESSFUL 7/12 DELIVERY TECHNICAL SUMMARY")
        print("==================================================")
        print(f"Operator Confirmed Result Visible? {operator_confirmed}")
        print(f"Popup / New Tab After Submit?       {delivery['popup_after_submit']} (Count: {delivery['popup_count']})")
        print(f"Native Download Occurred?          {delivery['download_event_triggered']}")
        print(f"Main Page Final URL:               {delivery['main_page_final_url']}")
        if delivery["popup_urls"]:
            print(f"Popup Base URLs:                   {delivery['popup_urls']}")
        print(f"Page Titles:                       {delivery['page_titles']}")
        print(f"IFrame Count:                      {delivery['iframe_count']} (Sources: {delivery['iframe_sources']})")
        print(f"Embed / Object Present?             {delivery['embed_object_present']}")
        print(f"PDF Viewer Detected?                {delivery['pdf_viewer_detected']}")
        print(f"HTML Document Rendered?            {delivery['html_document']}")
        print(f"Print Control Present?             {delivery['print_control_present']}")

        print("\n--- SESSION PERSISTENCE ---")
        print(f"Original Main Page Open?           {session_info.get('original_page_available')}")
        print(f"District Selection Preserved?       {session_info.get('district_preserved')}")
        print(f"Taluka Selection Preserved?         {session_info.get('taluka_preserved')}")
        print(f"Village Selection Preserved?        {session_info.get('village_preserved')}")
        print(f"Survey Selection Preserved?         {session_info.get('survey_preserved')}")
        print(f"CAPTCHA Reset/Refreshed?           {session_info.get('captcha_reset')}")

        # Save Report JSON
        report = {
            "timestamp": datetime.now().isoformat(),
            "success": operator_confirmed,
            "operator_confirmed_result_visible": operator_confirmed,
            "pre_submit_boundary": {
                "district_selected": pre_state["districtSelected"],
                "taluka_selected": pre_state["talukaSelected"],
                "village_selected": pre_state["villageSelected"],
                "survey_selected": pre_state["surveySelected"],
                "survey_selected_text": pre_state.get("surveySelectedText"),
                "mobile_populated": pre_state["mobilePopulated"],
                "mobile_valid_format": pre_state["mobileValidFormat"],
                "captcha_populated": pre_state["captchaPopulated"]
            },
            "delivery": delivery,
            "session": session_info
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"successful_record_delivery_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Technical delivery report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
