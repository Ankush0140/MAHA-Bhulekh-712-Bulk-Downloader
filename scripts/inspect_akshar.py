import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Selectors
SELECT_SEARCH_TYPE = "#ContentPlaceHolder1_ddlSelectSearchType"
INPUT_PART1 = "#ContentPlaceHolder1_txtcsno"
BTN_SEARCH = "#ContentPlaceHolder1_btnsearchfind"
SELECT_SURVEY = "#ContentPlaceHolder1_ddlsurveyno"

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
LATIN_RE = re.compile(r"[a-zA-Z]")
DIGIT_RE = re.compile(r"\d")


def compute_signature(options: list[dict]) -> str:
    """Compute MD5 hash signature of option list for stale-state detection."""
    raw = "|".join([f"{opt['value']}:{opt['text']}" for opt in options])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def is_placeholder(opt: dict) -> bool:
    """Identify placeholder option."""
    text = opt.get("text", "").strip()
    val = opt.get("value", "").strip()
    return "निवडा" in text or val in ["0", "-1", ""]


async def get_dropdown_options(page: Page, selector: str) -> list[dict]:
    """Retrieve options from a select element."""
    try:
        return await page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (!el) return [];
            return Array.from(el.options).map(o => ({{
                text: o.text.trim(),
                value: o.value
            }}));
        }}""", selector)
    except Exception as e:
        print(f"[DROPDOWN ERROR] Could not read {selector}: {e}")
        return []


async def inspect_akshar_dom(page: Page) -> dict:
    """Inspect DOM state specifically in Akshar mode."""
    return await page.evaluate("""() => {
        const inputPart1 = document.querySelector('#ContentPlaceHolder1_txtcsno');
        const btnSearch = document.querySelector('#ContentPlaceHolder1_btnsearchfind');
        const selectSurvey = document.querySelector('#ContentPlaceHolder1_ddlsurveyno');
        const selectSearchType = document.querySelector('#ContentPlaceHolder1_ddlSelectSearchType');

        const allInputs = Array.from(document.querySelectorAll('input')).map(el => ({
            id: el.id || null,
            name: el.name || null,
            type: el.type || 'text',
            visible: el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none'
        }));

        return {
            searchTypeMode: selectSearchType ? selectSearchType.value : null,
            inputPart1Visible: inputPart1 ? (inputPart1.offsetWidth > 0 && window.getComputedStyle(inputPart1).display !== 'none') : false,
            btnSearchVisible: btnSearch ? (btnSearch.offsetWidth > 0 && window.getComputedStyle(btnSearch).display !== 'none') : false,
            selectSurveyVisible: selectSurvey ? (selectSurvey.offsetWidth > 0 && window.getComputedStyle(selectSurvey).display !== 'none') : false,
            allInputs: allInputs
        };
    }""")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Phase 2F — Akshar Discovery Test")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("MANUAL ACTION REQUIRED IN CHROME:")
        print("1. Select District (e.g. अमरावती)")
        print("2. Select Taluka (e.g. अमरावती)")
        print("3. Select Village (e.g. अंभोळा)")
        print("4. Select Search Mode: 'अक्षरी सर्वे नंबर' (value 8)")
        print("--------------------------------------------------")
        
        await asyncio.get_event_loop().run_in_executor(
            None, input, "After performing the manual selections, press ENTER to inspect DOM and run Search..."
        )

        # 1. DOM Inspection in Akshar Mode
        print("\n1. Inspecting DOM in Akshar Mode...")
        dom_info = await inspect_akshar_dom(page)
        print(f"   Search Mode Value: '{dom_info['searchTypeMode']}' (Expected '8')")
        print(f"   Part-1 Input Field Visible? {dom_info['inputPart1Visible']}")
        print(f"   Search Button Visible?       {dom_info['btnSearchVisible']}")
        print(f"   Survey Result Dropdown Visible? {dom_info['selectSurveyVisible']}")

        # 2. Capture Pre-Search State
        pre_options = await get_dropdown_options(page, SELECT_SURVEY)
        pre_sig = compute_signature(pre_options)
        print(f"2. Pre-search dropdown option count: {len(pre_options)} (Signature: {pre_sig[:8]})")

        # 3. Click Search Button ONCE without entering search term
        print(f"3. Clicking Search button ({BTN_SEARCH}) without search term...")
        start_time = time.time()
        response_status = None
        
        try:
            async with page.expect_response(
                lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
                timeout=30000
            ) as resp_info:
                await page.locator(BTN_SEARCH).click()

            response = await resp_info.value
            response_status = response.status
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(1.5)
        except Exception as e:
            print(f"[POSTBACK WARNING] Timeout/exception clicking Search in Akshar mode: {e}")

        elapsed_time = round(time.time() - start_time, 2)
        post_options = await get_dropdown_options(page, SELECT_SURVEY)
        post_sig = compute_signature(post_options)
        is_stale = (pre_sig == post_sig and len(pre_options) > 0)
        clean_options = [o for o in post_options if not is_placeholder(o)]

        print(f"\n4. Postback completed in {elapsed_time}s | HTTP Status: {response_status}")
        print(f"   Post-search Total Option Count: {len(post_options)}")
        print(f"   Post-search Clean Option Count: {len(clean_options)}")
        print(f"   Post-search Signature: {post_sig[:8]}")
        print(f"   Is Stale State? {is_stale}")

        # 4. Analyze Returned Options
        digit_count = 0
        slash_count = 0
        latin_count = 0
        devanagari_count = 0

        for opt in clean_options:
            txt = opt["text"]
            if DIGIT_RE.search(txt):
                digit_count += 1
            if "/" in txt:
                slash_count += 1
            if LATIN_RE.search(txt):
                latin_count += 1
            if DEVANAGARI_RE.search(txt):
                devanagari_count += 1

        print("\n--------------------------------------------------")
        print("AKSHAR DISCOVERY RESULTS ANALYSIS:")
        print("--------------------------------------------------")
        print(f"Total Clean Options: {len(clean_options)}")
        print(f"Options with Digits:      {digit_count}")
        print(f"Options with Slash '/':    {slash_count}")
        print(f"Options with Latin chars: {latin_count}")
        print(f"Options with Devanagari:  {devanagari_count}")

        if clean_options:
            print("\nFirst 20 Representative Options:")
            for opt in clean_options[:20]:
                print(f"  - Value: '{opt['value']}', Text: '{opt['text']}'")
        else:
            print("\nNO OPTIONS RETURNED! (Clicking Search without input did not populate dropdown)")

        # 5. Save Full Log
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "dom_info": dom_info,
            "search_execution": {
                "response_status": response_status,
                "elapsed_seconds": elapsed_time,
                "pre_count": len(pre_options),
                "post_count": len(post_options),
                "clean_count": len(clean_options),
                "pre_signature": pre_sig,
                "post_signature": post_sig,
                "is_stale": is_stale
            },
            "analysis": {
                "total_clean_options": len(clean_options),
                "digit_count": digit_count,
                "slash_count": slash_count,
                "latin_count": latin_count,
                "devanagari_count": devanagari_count,
                "first_20_samples": clean_options[:20]
            },
            "all_options": post_options
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = LOG_DIR / f"akshar_inspection_{timestamp_str}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Akshar investigation report saved to: {filepath}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
