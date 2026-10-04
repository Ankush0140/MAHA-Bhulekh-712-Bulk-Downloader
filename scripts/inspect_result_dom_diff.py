import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.config import TEST_MOBILE_NUMBER
import re

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"

JS_GET_VISIBLE_ELEMENTS = """
() => {
    const visibleEls = Array.from(document.querySelectorAll('*')).filter(e => {
        const style = window.getComputedStyle(e);
        return style.display !== 'none' && 
               style.visibility !== 'hidden' && 
               e.getBoundingClientRect().height > 0 && 
               e.getBoundingClientRect().width > 0;
    });
    return visibleEls.map(e => {
        const rect = e.getBoundingClientRect();
        return {
            tag: e.tagName,
            id: e.id,
            className: typeof e.className === 'string' ? e.className : '',
            height: Math.round(rect.height),
            width: Math.round(rect.width),
            textPreview: (e.innerText || '').substring(0, 50).replace(/\\n/g, ' ')
        };
    });
}
"""

async def main():
    print("==================================================")
    print("PHASE 5: PRE/POST DOM STRUCTURAL DIFF")
    print("==================================================")
    print("Launching Google Chrome...")

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
        print("DO NOT CLICK SUBMIT YET!")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nWhen form is complete (DO NOT CLICK SUBMIT), press ENTER here..."
        )

        print("\nCapturing pre-submit DOM state...")
        pre_elements = await page.evaluate(JS_GET_VISIBLE_ELEMENTS)
        print(f"Captured {len(pre_elements)} visible elements.")

        print("\n--------------------------------------------------")
        print("ACTION FOR OPERATOR:")
        print("1. Click Submit ONCE in Google Chrome.")
        print("2. Wait until the requested 7/12 extract is FULLY rendered.")
        print("3. Press ENTER in this terminal.")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter 7/12 is visible, press ENTER here..."
        )

        print("\nCapturing post-submit DOM state...")
        post_elements = await page.evaluate(JS_GET_VISIBLE_ELEMENTS)
        print(f"Captured {len(post_elements)} visible elements.")

        print("\nAnalyzing differences...")
        
        # Build ID sets
        pre_ids = {e['id'] for e in pre_elements if e['id']}
        post_ids = {e['id'] for e in post_elements if e['id']}
        
        new_ids = post_ids - pre_ids
        print(f"\nNew visible elements with IDs ({len(new_ids)}):")
        
        new_elements = [e for e in post_elements if e['id'] in new_ids]
        # Sort by height to find the main container
        new_elements.sort(key=lambda x: x['height'], reverse=True)
        
        for e in new_elements[:10]:
            print(f" - #{e['id']} (Tag: {e['tag']}, Size: {e['width']}x{e['height']}, Class: '{e['className']}')")
            print(f"   Text: {e['textPreview']}...")

        # Also find elements that were present but whose height increased significantly
        print("\nChecking for existing elements that expanded significantly (height diff > 200px):")
        pre_dict = {e['id']: e for e in pre_elements if e['id']}
        for e in post_elements:
            if e['id'] and e['id'] in pre_dict:
                old_h = pre_dict[e['id']]['height']
                new_h = e['height']
                if new_h - old_h > 200:
                    print(f" - #{e['id']} expanded from {old_h}px to {new_h}px (Tag: {e['tag']})")

        # Removed HTML saving for privacy reasons.

        print("\nClosing browser...")
        await context.close()
        await browser.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
