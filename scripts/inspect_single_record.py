import asyncio
import json
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

# Selectors for verification
SELECT_DISTRICT = "#ContentPlaceHolder1_ddlMainDist"
SELECT_TALUKA = "#ContentPlaceHolder1_ddlTalForAll"
SELECT_VILLAGE = "#ContentPlaceHolder1_ddlVillForAll"
SELECT_SURVEY = "#ContentPlaceHolder1_ddlsurveyno"
INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile"
INPUT_CAPTCHA = "#ContentPlaceHolder1_captcha"

captured_events = {
    "popups": [],
    "downloads": [],
    "responses": []
}


async def on_new_page(new_page: Page):
    try:
        url = new_page.url
        title = await new_page.title()
        captured_events["popups"].append({
            "timestamp": datetime.now().isoformat(),
            "url": url.split("?")[0],  # Strip query params for privacy
            "title": title
        })
        print(f"\n[EVENT] Popup / New Tab Opened! Title: '{title}' | URL Base: {url.split('?')[0]}")
    except Exception as e:
        print(f"[EVENT ERROR] New page event error: {e}")


async def on_download(download: Download):
    try:
        filename = download.suggested_filename
        captured_events["downloads"].append({
            "timestamp": datetime.now().isoformat(),
            "suggested_filename": filename,
            "url": download.url.split("?")[0]
        })
        print(f"\n[EVENT] Native Download Triggered! Filename: '{filename}'")
    except Exception as e:
        print(f"[EVENT ERROR] Download event error: {e}")


async def on_response(response: Response):
    try:
        url = response.url
        if "mahabhumi.gov.in" in url:
            content_type = response.headers.get("content-type", "")
            status = response.status
            # Capture relevant 7/12 or form submission responses
            if any(k in url.lower() for k in ["712", "report", "print", "display", "get", "view", "pdf"]):
                captured_events["responses"].append({
                    "timestamp": datetime.now().isoformat(),
                    "status": status,
                    "content_type": content_type,
                    "url": url.split("?")[0]
                })
                print(f"[NETWORK RES] {status} {url.split('?')[0]} ({content_type})")
    except Exception as e:
        print(f"[EVENT ERROR] Response listener error: {e}")


async def inspect_technical_delivery(main_page: Page, popup_pages: list[Page]) -> dict:
    """Inspect main page and any spawned popups for technical delivery attributes."""
    pages_to_check = [main_page] + popup_pages

    delivery_info = {
        "same_page_url_changed": False,
        "popup_count": len(popup_pages),
        "native_download_occurred": len(captured_events["downloads"]) > 0,
        "download_info": captured_events["downloads"],
        "popup_info": captured_events["popups"],
        "responses_captured": captured_events["responses"],
        "iframe_present": False,
        "iframe_count": 0,
        "embed_object_present": False,
        "pdf_viewer_detected": False,
        "image_document_detected": False,
        "print_control_present": False,
        "page_titles": []
    }

    for idx, pg in enumerate(pages_to_check):
        try:
            pg_title = await pg.title()
            delivery_info["page_titles"].append(pg_title)

            # Technical DOM analysis without inspecting land record content
            dom_analysis = await pg.evaluate("""() => {
                const iframes = document.querySelectorAll('iframe, frame');
                const embeds = document.querySelectorAll('embed, object');
                const pdfViewers = document.querySelectorAll('embed[type*="pdf"], object[type*="pdf"], iframe[src*=".pdf"]');
                const images = document.querySelectorAll('img');
                
                const bodyText = document.body ? document.body.innerText.toLowerCase() : '';
                const hasPrintText = bodyText.includes('print') || bodyText.includes('छापा') || bodyText.includes('मुद्रण');
                const hasPrintBtn = document.querySelectorAll('button, input[type="button"], a').length > 0 &&
                                   Array.from(document.querySelectorAll('button, input[type="button"], a')).some(
                                       el => (el.innerText || el.value || '').toLowerCase().includes('print') || (el.innerText || el.value || '').includes('छापा')
                                   );

                return {
                    iframeCount: iframes.length,
                    embedCount: embeds.length,
                    pdfViewerCount: pdfViewers.length,
                    imageCount: images.length,
                    hasPrintControl: hasPrintText || hasPrintBtn
                };
            }""")

            if dom_analysis["iframeCount"] > 0:
                delivery_info["iframe_present"] = True
                delivery_info["iframe_count"] += dom_analysis["iframeCount"]
            if dom_analysis["embedCount"] > 0:
                delivery_info["embed_object_present"] = True
            if dom_analysis["pdfViewerCount"] > 0:
                delivery_info["pdf_viewer_detected"] = True
            if dom_analysis["hasPrintControl"]:
                delivery_info["print_control_present"] = True

        except Exception as e:
            print(f"[INSPECT WARNING] Page inspection error on page {idx}: {e}")

    return delivery_info


async def check_session_persistence(page: Page) -> dict:
    """Check if form controls retain selection after submit/postback."""
    try:
        return await page.evaluate("""() => {
            const dist = document.querySelector('#ContentPlaceHolder1_ddlMainDist');
            const tal = document.querySelector('#ContentPlaceHolder1_ddlTalForAll');
            const vill = document.querySelector('#ContentPlaceHolder1_ddlVillForAll');
            const survey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
            const captchaImg = document.querySelector('#ContentPlaceHolder1_imgCaptcha');

            return {
                districtSelected: dist ? (dist.selectedIndex > 0) : false,
                talukaSelected: tal ? (tal.selectedIndex > 0) : false,
                villageSelected: vill ? (vill.selectedIndex > 0) : false,
                surveySelected: survey ? (survey.selectedIndex > 0) : false,
                captchaImagePresent: captchaImg ? (captchaImg.offsetWidth > 0) : false
            };
        }""")
    except Exception as e:
        print(f"[PERSISTENCE ERROR] Error checking persistence: {e}")
        return {}


async def main():
    print("==================================================")
    print("MAHA Bhulekh Single 7/12 Record Retrieval Inspector")
    print("==================================================")
    print("Launching Google Chrome...")

    popup_pages = []

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        
        # Attach popup page listener
        context.on("page", lambda new_page: popup_pages.append(new_page))
        context.on("page", on_new_page)

        page = await context.new_page()
        page.on("download", on_download)
        page.on("response", on_response)

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # Autofill test mobile number if configured
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"\n[CONFIG] Authorized test mobile number detected in config: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
        print("1. In Chrome, select: Pune -> Maval -> Shivali")
        print("2. Select ONE simple numeric Survey/Gat Number from dropdown.")
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"3. Fill mobile number '{TEST_MOBILE_NUMBER.strip()}' (or let script fill it).")
            try:
                if await page.locator(INPUT_MOBILE).is_visible():
                    await page.locator(INPUT_MOBILE).fill(TEST_MOBILE_NUMBER.strip())
                    print("   -> Mobile number filled automatically into field.")
            except Exception:
                pass
        else:
            print("3. Enter authorized test mobile number manually (1234567890).")
        print("4. Read and enter CAPTCHA manually into the CAPTCHA field.")
        print("5. Click Submit in Chrome to request the 7/12 record.")
        print("6. Wait until the 7/12 result appears (or error message appears).")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter submitting and waiting for 7/12 result to appear in Chrome, press ENTER here..."
        )

        print("\nAnalyzing technical delivery mechanism & session persistence...")
        delivery = await inspect_technical_delivery(page, popup_pages)
        persistence = await check_session_persistence(page)

        print("\n==================================================")
        print("TECHNICAL DELIVERY ANALYSIS")
        print("==================================================")
        print(f"Popup / New Tab Spawned?       {delivery['popup_count'] > 0} (Count: {delivery['popup_count']})")
        print(f"Native Download Occurred?      {delivery['native_download_occurred']}")
        print(f"IFrame Present?                 {delivery['iframe_present']} (Count: {delivery['iframe_count']})")
        print(f"Embed / Object Present?         {delivery['embed_object_present']}")
        print(f"PDF Viewer Detected?            {delivery['pdf_viewer_detected']}")
        print(f"Print Control / UI Present?     {delivery['print_control_present']}")
        print(f"Page Titles Observed:           {delivery['page_titles']}")

        print("\n--- SESSION PERSISTENCE ---")
        print(f"District Selection Preserved?   {persistence.get('districtSelected')}")
        print(f"Taluka Selection Preserved?     {persistence.get('talukaSelected')}")
        print(f"Village Selection Preserved?    {persistence.get('villageSelected')}")
        print(f"Survey Selection Preserved?     {persistence.get('surveySelected')}")

        # Save technical JSON
        report = {
            "timestamp": datetime.now().isoformat(),
            "delivery": delivery,
            "session_persistence": persistence
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"single_record_delivery_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Technical delivery report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
