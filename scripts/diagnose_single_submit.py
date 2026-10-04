import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, Response, Download, Dialog

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
SELECT_SEARCH_TYPE = "#ContentPlaceHolder1_ddlSelectSearchType"
SELECT_SURVEY = "#ContentPlaceHolder1_ddlsurveyno"
INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile"
INPUT_CAPTCHA = "#ContentPlaceHolder1_captcha"

# Verified submit button candidates
BTN_SUBMIT_PRIMARY = "#ContentPlaceHolder1_btnmainsubmit"
BTN_SUBMIT_ALT = "#ContentPlaceHolder1_btnGet712"

# Event state buffers (populated strictly AFTER submit boundary)
post_submit_events = {
    "post_requests": [],
    "popups": [],
    "downloads": [],
    "dialogs": [],
    "console_errors": [],
    "page_errors": []
}


async def inspect_pre_submit_state(page: Page) -> dict:
    """Inspect form state and submit button attributes BEFORE submit (booleans only)."""
    return await page.evaluate("""() => {
        const dist = document.querySelector('#ContentPlaceHolder1_ddlMainDist');
        const tal = document.querySelector('#ContentPlaceHolder1_ddlTalForAll');
        const vill = document.querySelector('#ContentPlaceHolder1_ddlVillForAll');
        const searchType = document.querySelector('#ContentPlaceHolder1_ddlSelectSearchType');
        const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
        const mobile = document.querySelector('#ContentPlaceHolder1_txtmobile');
        const captcha = document.querySelector('#ContentPlaceHolder1_captcha');

        // Check submit button candidates
        const btn1 = document.querySelector('#ContentPlaceHolder1_btnmainsubmit');
        const btn2 = document.querySelector('#ContentPlaceHolder1_btnGet712');
        const btn = btn1 || btn2 || Array.from(document.querySelectorAll('input[type="submit"], button')).find(b => (b.value || b.innerText || '').includes('7/12') || (b.id || '').toLowerCase().includes('submit'));

        const submitInfo = btn ? {
            exists: true,
            selectorUsed: btn1 ? '#ContentPlaceHolder1_btnmainsubmit' : (btn2 ? '#ContentPlaceHolder1_btnGet712' : btn.id || btn.tagName),
            tagName: btn.tagName,
            type: btn.type || null,
            id: btn.id || null,
            name: btn.name || null,
            value: btn.value || btn.innerText || null,
            visible: btn.offsetWidth > 0 && btn.offsetHeight > 0 && window.getComputedStyle(btn).display !== 'none',
            enabled: !btn.disabled,
            hasOnClick: !!btn.onclick || btn.hasAttribute('onclick'),
            onclickSnippet: btn.getAttribute('onclick') ? btn.getAttribute('onclick').slice(0, 100) : null
        } : { exists: false };

        const surveySelected = survey ? (survey.selectedIndex > 0 && survey.value !== '0' && survey.value !== '') : false;
        const surveyValueText = survey && survey.selectedIndex >= 0 ? survey.options[survey.selectedIndex].text : '';

        return {
            districtSelected: dist ? (dist.selectedIndex > 0) : false,
            talukaSelected: tal ? (tal.selectedIndex > 0) : false,
            villageSelected: vill ? (vill.selectedIndex > 0) : false,
            numericModeSelected: searchType ? (searchType.value === '2') : false,
            surveySelected: surveySelected,
            surveySelectedText: surveyValueText,
            mobilePopulated: mobile ? (mobile.value.trim().length > 0) : false,
            captchaPopulated: captcha ? (captcha.value.trim().length > 0) : false,
            submitInfo: submitInfo
        };
    }""")


async def inspect_visible_validation_messages(page: Page) -> list[str]:
    """Check for visible client-side or server-side validation error messages."""
    return await page.evaluate("""() => {
        const errorNodes = Array.from(document.querySelectorAll('.error, .validation, span[id*="val"], span[id*="err"], span[id*="rfv"], div[style*="color:Red"], span[style*="color:Red"], font[color="red"]'));
        return errorNodes
            .filter(el => el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none')
            .map(el => el.innerText.trim())
            .filter(txt => txt.length > 0);
    }""")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Single Submit Diagnostic Tool")
    print("==================================================")
    print("Launching Google Chrome...")

    popup_pages_after_submit = []

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Autofill test mobile number if available in environment
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"\n[CONFIG] Authorized test mobile number detected: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
        print("1. In Chrome, select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE simple numeric Survey/Gat Number from dropdown.")
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print("3. Mobile number will auto-fill (or type authorized test mobile 1234567890).")
            try:
                if await page.locator(INPUT_MOBILE).is_visible():
                    await page.locator(INPUT_MOBILE).fill(TEST_MOBILE_NUMBER.strip())
            except Exception:
                pass
        else:
            print("3. Enter authorized test mobile number manually (1234567890).")
        print("4. Read and enter CAPTCHA manually into the CAPTCHA field.")
        print("--------------------------------------------------")
        print("DO NOT CLICK SUBMIT YET!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nWhen form & CAPTCHA are complete (DO NOT CLICK SUBMIT YET), press ENTER here..."
        )

        # STEP 1: PRE-SUBMIT INSPECTION AT BOUNDARY
        print("\n1. Capturing Pre-Submit Form State (Boundary Check)...")
        pre_state = await inspect_pre_submit_state(page)

        print("\n--- PRE-SUBMIT CHECK ---")
        print(f"District Selected?      {pre_state['districtSelected']}")
        print(f"Taluka Selected?        {pre_state['talukaSelected']}")
        print(f"Village Selected?       {pre_state['villageSelected']}")
        print(f"Numeric Mode Selected? {pre_state['numericModeSelected']}")
        print(f"Survey Record Selected? {pre_state['surveySelected']} (Selected Text: '{pre_state.get('surveySelectedText')}')")
        print(f"Mobile Field Populated: {pre_state['mobilePopulated']}  [BOOLEAN ONLY]")
        print(f"CAPTCHA Field Populated: {pre_state['captchaPopulated']}  [BOOLEAN ONLY]")
        
        sinfo = pre_state["submitInfo"]
        if sinfo.get("exists"):
            print(f"Submit Element Found:   Selector='{sinfo['selectorUsed']}' | Visible={sinfo['visible']} | Enabled={sinfo['enabled']} | Type='{sinfo['type']}'")
            if sinfo.get("onclickSnippet"):
                print(f"OnClick Snippet:        '{sinfo['onclickSnippet']}'")
        else:
            print("WARNING: No Submit button element found!")

        pre_url = page.url
        pre_title = await page.title()

        # STEP 2: INSTALL POST-SUBMIT LISTENERS ONLY AFTER ENTER
        print("\n2. Resetting event buffers & activating POST-SUBMIT diagnostic listeners...")

        def on_post_submit_page(new_pg: Page):
            popup_pages_after_submit.append(new_pg)
            try:
                post_submit_events["popups"].append({
                    "timestamp": datetime.now().isoformat(),
                    "url_base": new_pg.url.split("?")[0],
                })
                print(f"\n[POST-SUBMIT POPUP EVENT] New Tab/Popup Opened! URL Base: {new_pg.url.split('?')[0]}")
            except Exception as e:
                print(f"[POPUP ERR] {e}")

        def on_post_submit_download(dload: Download):
            post_submit_events["downloads"].append({
                "timestamp": datetime.now().isoformat(),
                "suggested_filename": dload.suggested_filename
            })
            print(f"\n[POST-SUBMIT DOWNLOAD EVENT] Download Triggered! Filename: {dload.suggested_filename}")

        def on_post_submit_dialog(dialog: Dialog):
            post_submit_events["dialogs"].append({
                "timestamp": datetime.now().isoformat(),
                "type": dialog.type,
                "message": dialog.message
            })
            print(f"\n[POST-SUBMIT DIALOG EVENT] Dialog Alert! Type: '{dialog.type}' | Message: '{dialog.message}'")

        def on_post_submit_response(response: Response):
            try:
                url = response.url
                if "mahabhumi.gov.in" in url:
                    if response.request.method == "POST":
                        post_submit_events["post_requests"].append({
                            "timestamp": datetime.now().isoformat(),
                            "status": response.status,
                            "content_type": response.headers.get("content-type", ""),
                            "url_base": url.split("?")[0]
                        })
                        print(f"[POST-SUBMIT NETWORK POST] HTTP {response.status} {url.split('?')[0]} ({response.headers.get('content-type', '')})")
            except Exception:
                pass

        def on_console_msg(msg):
            if msg.type == "error":
                post_submit_events["console_errors"].append(msg.text)
                print(f"[CONSOLE ERROR] {msg.text}")

        def on_page_error(err):
            post_submit_events["page_errors"].append(str(err))
            print(f"[PAGE ERROR] {err}")

        context.on("page", on_post_submit_page)
        page.on("download", on_post_submit_download)
        page.on("dialog", on_post_submit_dialog)
        page.on("response", on_post_submit_response)
        page.on("console", on_console_msg)
        page.on("pageerror", on_page_error)

        print("\n--------------------------------------------------")
        print("ACTION FOR HUMAN OPERATOR:")
        print("1. Click Submit ONCE in Google Chrome.")
        print("2. Observe the browser behavior for 10-15 seconds.")
        print("3. Press ENTER in this terminal when finished.")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter clicking Submit and observing Chrome for 10-15 seconds, press ENTER here..."
        )

        # STEP 3: POST-SUBMIT DIAGNOSTIC ANALYSIS
        print("\n3. Analyzing Post-Submit Diagnostic Evidence...")
        post_url = page.url
        post_title = await page.title()
        url_changed = (post_url != pre_url)

        validation_msgs = await inspect_visible_validation_messages(page)

        # Check post-submit submit button state
        post_submit_btn_state = await page.evaluate("""() => {
            const btn = document.querySelector('#ContentPlaceHolder1_btnmainsubmit') || document.querySelector('#ContentPlaceHolder1_btnGet712');
            return btn ? { disabled: btn.disabled, visible: btn.offsetWidth > 0 } : null;
        }""")

        post_request_observed = len(post_submit_events["post_requests"]) > 0
        popup_after_submit = len(post_submit_events["popups"]) > 0
        download_after_submit = len(post_submit_events["downloads"]) > 0
        dialog_observed = len(post_submit_events["dialogs"]) > 0

        # Classification
        classification = "INCONCLUSIVE"
        if not post_request_observed and not popup_after_submit and not download_after_submit:
            classification = "SUBMISSION_FAILED_NO_POST"
        elif any("captcha" in m.lower() or "अवैध" in m or "चुकी" in m for m in validation_msgs):
            classification = "CAPTCHA_REJECTED"
        elif download_after_submit or popup_after_submit or url_changed:
            classification = "POTENTIAL_RESULT_DELIVERED"

        print("\n==================================================")
        print("POST-SUBMIT DIAGNOSTIC EVIDENCE SUMMARY")
        print("==================================================")
        print(f"Classification:                {classification}")
        print(f"POST Request Observed?         {post_request_observed}")
        if post_submit_events["post_requests"]:
            req = post_submit_events["post_requests"][0]
            print(f"   POST Status: {req['status']} | Content-Type: {req['content_type']}")
        print(f"URL Changed?                   {url_changed} (Pre: {pre_url.split('?')[0]} -> Post: {post_url.split('?')[0]})")
        print(f"Popup / New Tab After Submit?   {popup_after_submit} (Count: {len(post_submit_events['popups'])})")
        print(f"Native Download After Submit?  {download_after_submit}")
        print(f"Dialog Alert Observed?         {dialog_observed}")
        if post_submit_events["dialogs"]:
            print(f"   Dialog Msg: {post_submit_events['dialogs'][0]['message']}")
        print(f"Visible Validation Messages:   {validation_msgs}")
        print(f"Console Errors Count:          {len(post_submit_events['console_errors'])}")

        # Save diagnostic JSON
        report = {
            "timestamp": datetime.now().isoformat(),
            "pre_submit": {
                "district_selected": pre_state["districtSelected"],
                "taluka_selected": pre_state["talukaSelected"],
                "village_selected": pre_state["villageSelected"],
                "numeric_mode_selected": pre_state["numericModeSelected"],
                "survey_selected": pre_state["surveySelected"],
                "survey_selected_text": pre_state.get("surveySelectedText"),
                "mobile_populated": pre_state["mobilePopulated"],
                "captcha_populated": pre_state["captchaPopulated"],
                "submit_button": pre_state["submitInfo"]
            },
            "post_submit": {
                "post_request_observed": post_request_observed,
                "post_requests": post_submit_events["post_requests"],
                "url_changed": url_changed,
                "popup_after_submit": popup_after_submit,
                "popups": post_submit_events["popups"],
                "download_after_submit": download_after_submit,
                "downloads": post_submit_events["downloads"],
                "dialog_observed": dialog_observed,
                "dialogs": post_submit_events["dialogs"],
                "validation_messages": validation_msgs,
                "console_errors": post_submit_events["console_errors"],
                "page_errors": post_submit_events["page_errors"],
                "submit_button_post_state": post_submit_btn_state
            },
            "classification": classification
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"single_submit_diagnostic_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Diagnostic report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
