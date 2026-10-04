import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, Frame

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.config import TEST_MOBILE_NUMBER

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)


async def inventory_pages_and_frames(context) -> dict:
    """Enumerate all pages and frames in the Playwright browser context."""
    pages_info = []
    for p_idx, p in enumerate(context.pages):
        frames_info = []
        for f_idx, f in enumerate(p.frames):
            try:
                has_dist = await f.locator("#ContentPlaceHolder1_ddlMainDist").count() > 0
                has_mobile1 = await f.locator("#ContentPlaceHolder1_txtmobile1").count() > 0
                has_mobile = await f.locator("#ContentPlaceHolder1_txtmobile").count() > 0
                has_captcha = await f.locator("#ContentPlaceHolder1_captcha, #ContentPlaceHolder1_txtcaptcha").count() > 0
            except Exception:
                has_dist = has_mobile1 = has_mobile = has_captcha = False

            frames_info.append({
                "frame_index": f_idx,
                "name": f.name,
                "url_base": f.url.split("?")[0],
                "has_district_select": has_dist,
                "has_mobile1_input": has_mobile1,
                "has_mobile_input": has_mobile,
                "has_captcha_input": has_captcha
            })

        try:
            p_title = await p.title()
        except Exception:
            p_title = "Unknown"

        pages_info.append({
            "page_index": p_idx,
            "url_base": p.url.split("?")[0],
            "title": p_title,
            "frames": frames_info
        })

    return {"pages": pages_info}


async def inventory_element_matches(page: Page, selectors: list[str]) -> list[dict]:
    """Inventory elements matching given selector candidates without returning values."""
    combined_selector = ", ".join(selectors)
    return await page.evaluate(f"""(sel) => {{
        const elements = Array.from(document.querySelectorAll(sel));
        return elements.map((el, idx) => {{
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            return {{
                match_index: idx,
                tagName: el.tagName,
                id: el.id || null,
                name: el.name || null,
                type: el.type || null,
                maxLength: el.maxLength >= 0 ? el.maxLength : null,
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
                enabled: !el.disabled,
                readOnly: el.readOnly || false,
                hasBoundingBox: rect.width > 0 && rect.height > 0,
                hasValue: (el.value || '').trim().length > 0
            }};
        }});
    }}""", combined_selector)


async def check_field_population_safe(page: Page) -> dict:
    """Safe check of population state for mobile and CAPTCHA fields (booleans & lengths ONLY)."""
    return await page.evaluate("""() => {
        // Query all potential mobile input elements
        const mobileCandidates = Array.from(document.querySelectorAll('input[id*="mobile"], input[name*="mobile"], #ContentPlaceHolder1_txtmobile1, #ContentPlaceHolder1_txtmobile'));
        const visibleMobile = mobileCandidates.find(el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        }) || mobileCandidates[0];

        // Query all potential captcha input elements
        const captchaCandidates = Array.from(document.querySelectorAll('input[id*="captcha"], input[name*="captcha"], #ContentPlaceHolder1_txtcaptcha, #ContentPlaceHolder1_captcha'));
        const visibleCaptcha = captchaCandidates.find(el => {
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
        }) || captchaCandidates[0];

        const mobileVal = visibleMobile ? (visibleMobile.value || '').trim() : '';
        const captchaVal = visibleCaptcha ? (visibleCaptcha.value || '').trim() : '';

        return {
            mobileFieldFound: !!visibleMobile,
            mobileElementId: visibleMobile ? visibleMobile.id : null,
            mobileElementName: visibleMobile ? visibleMobile.name : null,
            mobilePopulated: mobileVal.length > 0,
            mobileLength: mobileVal.length,
            mobileIs10Digits: mobileVal.length === 10 && /^\\d{10}$/.test(mobileVal),
            
            captchaFieldFound: !!visibleCaptcha,
            captchaElementId: visibleCaptcha ? visibleCaptcha.id : null,
            captchaElementName: visibleCaptcha ? visibleCaptcha.name : null,
            captchaPopulated: captchaVal.length > 0,
            captchaLength: captchaVal.length
        };
    }""")


async def inspect_validate_mobile_number_js(page: Page) -> dict:
    """Safely inspect validateMobileNumber JS function definition and missing referenced IDs."""
    return await page.evaluate("""() => {
        if (typeof window.validateMobileNumber !== 'function') {
            return { exists: false, reason: "Function validateMobileNumber does not exist in window scope" };
        }

        const fnString = window.validateMobileNumber.toString();

        // Extract getElementById references in function
        const getElemMatches = Array.from(fnString.matchAll(/document\.getElementById\s*\(\s*['"]([^'"]+)['"]\s*\)/g)).map(m => m[1]);
        const uniqueIds = Array.from(new Set(getElemMatches));

        const idStatus = uniqueIds.map(id => ({
            id: id,
            foundInDOM: !!document.getElementById(id),
            elementTagName: document.getElementById(id) ? document.getElementById(id).tagName : null
        }));

        const missingIds = idStatus.filter(item => !item.foundInDOM).map(item => item.id);

        return {
            exists: true,
            fnSnippet: fnString.slice(0, 300),
            referencedIds: idStatus,
            missingReferencedIds: missingIds,
            hasNullReferenceRisk: missingIds.length > 0
        };
    }""")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Form & Field Identity Diagnostic")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # STEP 1: Page & Frame Inventory
        print("\n--- STEP 1: PAGE AND FRAME INVENTORY ---")
        inventory = await inventory_pages_and_frames(context)
        for pg in inventory["pages"]:
            print(f"Page [{pg['page_index']}] URL: {pg['url_base']} | Title: '{pg['title']}' | Frames: {len(pg['frames'])}")
            for fr in pg["frames"]:
                print(f"   Frame [{fr['frame_index']}] Name: '{fr['name']}' | URL: {fr['url_base']} | DistSelect={fr['has_district_select']} | Mobile1={fr['has_mobile1_input']} | Mobile={fr['has_mobile_input']} | Captcha={fr['has_captcha_input']}")

        # STEP 2: Mobile Element Inventory
        print("\n--- STEP 2: MOBILE INPUT ELEMENT INVENTORY ---")
        mobile_selectors = [
            "#ContentPlaceHolder1_txtmobile",
            "#ContentPlaceHolder1_txtmobile1",
            "input[name*='txtmobile']",
            "input[name*='mobile']",
            "input[id*='mobile']"
        ]
        mobile_matches = await inventory_element_matches(page, mobile_selectors)
        print(f"Total Matching Mobile Elements Found: {len(mobile_matches)}")
        for m in mobile_matches:
            print(f"   Match [{m['match_index']}] Tag: {m['tagName']} | ID: '{m['id']}' | Name: '{m['name']}' | Visible: {m['visible']} | Enabled: {m['enabled']} | MaxLen: {m['maxLength']}")

        # STEP 3: Captcha Input Inventory
        print("\n--- STEP 3: CAPTCHA INPUT ELEMENT INVENTORY ---")
        captcha_selectors = [
            "#ContentPlaceHolder1_txtcaptcha",
            "#ContentPlaceHolder1_captcha",
            "input[name*='captcha']",
            "input[id*='captcha']"
        ]
        captcha_matches = await inventory_element_matches(page, captcha_selectors)
        print(f"Total Matching CAPTCHA Elements Found: {len(captcha_matches)}")
        for c in captcha_matches:
            print(f"   Match [{c['match_index']}] Tag: {c['tagName']} | ID: '{c['id']}' | Name: '{c['name']}' | Visible: {c['visible']} | Enabled: {c['enabled']} | MaxLen: {c['maxLength']}")

        # STEP 4: Human Form Setup
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"\n[CONFIG] Test mobile number configured: '******{TEST_MOBILE_NUMBER[-4:]}'")

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
        print("1. Select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE Survey/Gat Number from dropdown.")
        if TEST_MOBILE_NUMBER and TEST_MOBILE_NUMBER.strip():
            print(f"3. Autofilling mobile number into visible mobile input fields...")
            try:
                # Fill all visible mobile inputs automatically
                for m in mobile_matches:
                    if m["visible"] and m["id"]:
                        await page.locator(f"#{m['id']}").fill(TEST_MOBILE_NUMBER.strip())
                        print(f"   -> Filled mobile into #{m['id']}")
            except Exception as e:
                print(f"   -> Autofill exception: {e}")
        else:
            print("3. Enter authorized test mobile number manually (1234567890).")
        print("4. Read and enter CAPTCHA manually into the CAPTCHA field.")
        print("--------------------------------------------------")
        print("DO NOT CLICK SUBMIT!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter both mobile & CAPTCHA are filled (DO NOT CLICK SUBMIT), press ENTER here..."
        )

        # STEP 5: Safe Field Population Check
        print("\n--- STEP 5: FIELD POPULATION CHECK (SAFE) ---")
        pop_check = await check_field_population_safe(page)
        print(f"Mobile Field Target ID:     '{pop_check['mobileElementId']}' | Name: '{pop_check['mobileElementName']}'")
        print(f"Mobile Field Populated?     {pop_check['mobilePopulated']}  [BOOLEAN ONLY]")
        print(f"Mobile String Length:       {pop_check['mobileLength']} characters")
        print(f"Mobile Shape Valid (10-digit)? {pop_check['mobileIs10Digits']}")

        print(f"\nCAPTCHA Field Target ID:    '{pop_check['captchaElementId']}' | Name: '{pop_check['captchaElementName']}'")
        print(f"CAPTCHA Field Populated?    {pop_check['captchaPopulated']}  [BOOLEAN ONLY]")
        print(f"CAPTCHA String Length:      {pop_check['captchaLength']} characters")

        # STEP 6: Wait 3 seconds and recheck for JS clearing
        print("\n--- STEP 6: WAITING 3 SECONDS & RECHECKING FIELD STABILITY ---")
        await asyncio.sleep(3.0)
        recheck = await check_field_population_safe(page)
        print(f"Mobile Still Populated?     {recheck['mobilePopulated']} (Length: {recheck['mobileLength']})")
        print(f"CAPTCHA Still Populated?    {recheck['captchaPopulated']} (Length: {recheck['captchaLength']})")

        # STEP 8: Inspect validateMobileNumber JS Definition
        print("\n--- STEP 8: VALIDATION FUNCTION INSPECTION (validateMobileNumber) ---")
        val_js = await inspect_validate_mobile_number_js(page)
        if val_js.get("exists"):
            print(f"Function validateMobileNumber Found: YES")
            print(f"Snippet: '{val_js['fnSnippet']}'")
            print(f"Referenced DOM IDs: {val_js['referencedIds']}")
            print(f"MISSING Referenced IDs: {val_js['missingReferencedIds']}")
            if val_js["missingReferencedIds"]:
                print(f"--> CRITICAL CAUSE FOUND: validateMobileNumber() fails with null.value because DOM element(s) {val_js['missingReferencedIds']} DO NOT EXIST on the page!")
        else:
            print(f"Function validateMobileNumber Found: NO ({val_js.get('reason')})")

        # STEP 9: Save Report (No Submission)
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "inventory": inventory,
            "mobile_matches": mobile_matches,
            "captcha_matches": captcha_matches,
            "population_check_1": pop_check,
            "population_check_2_after_3s": recheck,
            "validate_mobile_number_js": val_js
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"form_fields_diagnostic_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Form fields diagnostic report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
