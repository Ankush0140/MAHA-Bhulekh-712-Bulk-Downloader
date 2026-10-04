import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.config import TEST_MOBILE_NUMBER

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

INPUT_MOBILE = "#ContentPlaceHolder1_txtmobile1"


async def inspect_result_dom_structure(page: Page) -> dict:
    """Safely inspect candidate 7/12 DOM containers without logging personal record text."""
    return await page.evaluate("""() => {
        // Find containers that might hold the 7/12 record
        const allDivs = Array.from(document.querySelectorAll('div, section, main, table, form, pnl'));
        
        const candidateContainers = allDivs.filter(el => {
            const rect = el.getBoundingClientRect();
            if (rect.width < 100 || rect.height < 100) return false;

            const text = (el.innerText || '').toLowerCase();
            const hasBackBtn = text.includes('मागे जा') || text.includes('back');
            const has712Keywords = text.includes('7/12') || text.includes('सातबारा') || text.includes('गाव नमुना');
            const idMatch = (el.id || '').toLowerCase().includes('712') || (el.id || '').toLowerCase().includes('report') || (el.id || '').toLowerCase().includes('print');
            const classMatch = (el.className || '').toLowerCase().includes('712') || (el.className || '').toLowerCase().includes('report') || (el.className || '').toLowerCase().includes('print');

            return hasBackBtn || has712Keywords || idMatch || classMatch;
        });

        const candidatesInfo = candidateContainers.map((el, idx) => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const text = el.innerText || '';

            // Build parent hierarchy
            const parents = [];
            let curr = el.parentElement;
            while (curr && curr.tagName !== 'BODY') {
                const parentDescriptor = curr.tagName.toLowerCase() + (curr.id ? '#' + curr.id : '') + (curr.className ? '.' + curr.className.split(' ').join('.') : '');
                parents.push(parentDescriptor);
                curr = curr.parentElement;
            }

            return {
                candidateIndex: idx,
                tagName: el.tagName,
                id: el.id || null,
                className: el.className || null,
                dimensions: {
                    width: rect.width,
                    height: rect.height,
                    top: rect.top,
                    left: rect.left
                },
                visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
                positionStyle: style.position,
                displayStyle: style.display,
                childElementCount: el.childElementCount,
                hasBackButton: text.includes('मागे जा') || text.includes('back'),
                containsSearchFormControls: !!el.querySelector('#ContentPlaceHolder1_ddlMainDist, #ContentPlaceHolder1_btnmainsubmit'),
                parentHierarchy: parents.slice(0, 5)
            };
        });

        // Search form container info
        const searchFormContainer = document.querySelector('#ContentPlaceHolder1_UpdatePanel1') || document.querySelector('#form1') || document.querySelector('form');
        const searchFormInfo = searchFormContainer ? {
            id: searchFormContainer.id || null,
            tagName: searchFormContainer.tagName,
            visible: searchFormContainer.offsetWidth > 0 && searchFormContainer.offsetHeight > 0
        } : null;

        return {
            title: document.title,
            url_base: window.location.href.split('?')[0],
            searchFormContainer: searchFormInfo,
            candidates: candidatesInfo
        };
    }""")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Rendered 7/12 Result DOM Inspector")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("MANUAL INSTRUCTIONS FOR CHROME & OPERATOR:")
        print("1. Select: Pune -> Maval -> Shivali")
        print("2. Search & select ONE simple numeric Survey/Gat Number.")
        print("3. Enter a valid 10-digit Indian mobile number starting with 6-9.")
        print("4. Read and enter CAPTCHA manually into the field.")
        print("5. Click Submit in Chrome.")
        print("6. Wait until the requested 7/12 is visibly rendered on the page.")
        print("--------------------------------------------------")

        await asyncio.get_event_loop().run_in_executor(
            None, input, "\nAfter the 7/12 record is visibly rendered in Chrome, press ENTER here to inspect DOM structure..."
        )

        print("\nInspecting DOM structure of rendered result page (safe technical inspection)...")
        dom_report = await inspect_result_dom_structure(page)

        print("\n==================================================")
        print("CANDIDATE RESULT CONTAINER FINDINGS")
        print("==================================================")
        print(f"Page Title: {dom_report['title']}")
        print(f"Total Candidate Containers Found: {len(dom_report['candidates'])}")
        
        for c in dom_report["candidates"]:
            print(f"\nCandidate [{c['candidateIndex']}]: Tag={c['tagName']} | ID='{c['id']}' | Class='{c['className']}'")
            print(f"   Dimensions: {c['dimensions']['width']}x{c['dimensions']['height']} (Top: {c['dimensions']['top']}, Left: {c['dimensions']['left']})")
            print(f"   Position: {c['positionStyle']} | Display: {c['displayStyle']} | Children: {c['childElementCount']}")
            print(f"   Has 'मागे जा' (Back) Button? {c['hasBackButton']}")
            print(f"   Contains Search Form Controls? {c['containsSearchFormControls']}")
            print(f"   Parent Hierarchy: {' -> '.join(c['parentHierarchy'])}")

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"result_dom_structure_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(dom_report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] DOM structure report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
