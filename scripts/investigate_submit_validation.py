import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)


async def capture_validate_mobile_number_analysis(page: Page) -> dict:
    """Safely inspect validateMobileNumber JS function structure and element lookup conditions."""
    return await page.evaluate("""() => {
        if (typeof window.validateMobileNumber !== 'function') {
            return { exists: false, reason: "validateMobileNumber function not found in window object" };
        }

        const fnCode = window.validateMobileNumber.toString();

        // Extract all getElementById occurrences
        const matches = Array.from(fnCode.matchAll(/document\.getElementById\s*\(\s*['"]([^'"]+)['"]\s*\)/g)).map(m => m[1]);
        const uniqueIds = Array.from(new Set(matches));

        const referencedElementsAnalysis = uniqueIds.map(id => {
            const el = document.getElementById(id);
            return {
                targetId: id,
                existsInDOM: !!el,
                tagName: el ? el.tagName : null,
                visible: el ? (el.offsetWidth > 0 && el.offsetHeight > 0 && window.getComputedStyle(el).display !== 'none') : false
            };
        });

        // Extract alert messages in function
        const alertMatches = Array.from(fnCode.matchAll(/alert\s*\(\s*['"]([^'"]+)['"]\s*\)/g)).map(m => m[1]);

        return {
            exists: true,
            fullCodeSnippet: fnCode,
            referencedIds: uniqueIds,
            referencedElementsAnalysis: referencedElementsAnalysis,
            missingTargetIds: referencedElementsAnalysis.filter(item => !item.existsInDOM).map(item => item.targetId),
            alertMessages: alertMatches
        };
    }""")


async def check_record_type_controls(page: Page) -> dict:
    """Inspect record-type radio buttons/tabs (7/12, 8A, Property Card, K-Prat) and DOM field presence."""
    return await page.evaluate("""() => {
        const radioNodes = Array.from(document.querySelectorAll('input[type="radio"]')).map(r => ({
            id: r.id || null,
            name: r.name || null,
            value: r.value || null,
            checked: r.checked,
            label: r.labels && r.labels.length > 0 ? r.labels[0].innerText.trim() : (r.nextSibling ? r.nextSibling.textContent.trim() : null)
        }));

        const txtMobileExists = !!document.getElementById('ContentPlaceHolder1_txtmobile');
        const txtMobile1Exists = !!document.getElementById('ContentPlaceHolder1_txtmobile1');
        const txtMobileNoExists = !!document.getElementById('ContentPlaceHolder1_txtmobileno');

        return {
            recordTypeRadios: radioNodes,
            mobileFieldStatus: {
                ContentPlaceHolder1_txtmobile: txtMobileExists,
                ContentPlaceHolder1_txtmobile1: txtMobile1Exists,
                ContentPlaceHolder1_txtmobileno: txtMobileNoExists
            }
        };
    }""")


async def inspect_submit_buttons_and_form(page: Page) -> dict:
    """Inspect all submit button candidates and containing form attributes."""
    return await page.evaluate("""() => {
        const form = document.querySelector('form');
        const formInfo = form ? {
            id: form.id || null,
            action: form.action ? form.action.split('?')[0] : null,
            method: form.method || 'POST',
            hasOnSubmit: !!form.onsubmit
        } : null;

        const allSubmitButtons = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"]'))
            .filter(el => {
                const txt = (el.innerText || el.value || '').toLowerCase();
                const id = (el.id || '').toLowerCase();
                return txt.includes('submit') || txt.includes('search') || txt.includes('7/12') || id.includes('submit') || id.includes('btn');
            })
            .map(el => {
                const rect = el.getBoundingClientRect();
                return {
                    id: el.id || null,
                    name: el.name || null,
                    type: el.type || 'button',
                    text: (el.innerText || el.value || '').trim(),
                    visible: rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).display !== 'none',
                    enabled: !el.disabled,
                    onclick: el.getAttribute('onclick') || null,
                    parentContainerId: el.parentElement ? el.parentElement.id || el.parentElement.tagName : null
                };
            });

        return {
            formInfo: formInfo,
            submitButtons: allSubmitButtons
        };
    }""")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Submit Validation Root-Cause Investigation")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        # 1. Capture validateMobileNumber JS Definition & Structural Analysis
        print("\n1. Analyzing validateMobileNumber() JS Definition...")
        js_analysis = await capture_validate_mobile_number_analysis(page)
        
        if js_analysis.get("exists"):
            print(f"   Referenced DOM IDs in validateMobileNumber(): {js_analysis['referencedIds']}")
            print(f"   Target IDs present in DOM: {[item['targetId'] for item in js_analysis['referencedElementsAnalysis'] if item['existsInDOM']]}")
            print(f"   MISSING Target IDs: {js_analysis['missingTargetIds']}")
            print(f"   Alert Messages in function: {js_analysis['alertMessages']}")
            print("\n--- FUNCTION CODE SNIPPET ---")
            print(js_analysis["fullCodeSnippet"])
            print("-----------------------------\n")
        else:
            print(f"   WARNING: validateMobileNumber() function not found: {js_analysis.get('reason')}")

        # 2. Inspect Record Type Controls & Field Presence
        print("2. Inspecting Record Type Controls & DOM Field Presence...")
        rec_type_info = await check_record_type_controls(page)
        print("   Available Record Type Radios/Tabs:")
        for r in rec_type_info["recordTypeRadios"]:
            print(f"      - ID: '{r['id']}' | Value: '{r['value']}' | Label: '{r['label']}' | Checked: {r['checked']}")
        print(f"   Mobile Field ID Presence in 7/12 Mode: {rec_type_info['mobileFieldStatus']}")

        # 3. Inspect Submit Buttons & Form Markup
        print("\n3. Inspecting Submit Buttons & Form Markup...")
        buttons_info = await inspect_submit_buttons_and_form(page)
        print(f"   Form Info: {buttons_info['formInfo']}")
        print("   Submit Button Candidates:")
        for b in buttons_info["submitButtons"]:
            print(f"      - ID: '{b['id']}' | Text: '{b['text']}' | Visible: {b['visible']} | OnClick: '{b['onclick']}' | Container: '{b['parentContainerId']}'")

        # 4. Classification & Root-Cause Analysis
        missing_ids = js_analysis.get("missingTargetIds", [])
        if "ContentPlaceHolder1_txtmobile" in missing_ids or "ContentPlaceHolder1_txtmobileno" in missing_ids:
            classification = "C. RECORD-TYPE-SPECIFIC VALIDATION BUG / MISSING DOM FIELD"
            explanation = (
                "The live portal's JavaScript function `validateMobileNumber()` attempts to read `.value` "
                "from `document.getElementById('ContentPlaceHolder1_txtmobile')` or `document.getElementById('ContentPlaceHolder1_txtmobileno')` "
                "without checking if the elements exist. In 7/12 mode, the actual rendered text field is `ContentPlaceHolder1_txtmobile1`. "
                "Because `txtmobile` is null, calling `.value` throws a TypeError: Cannot read properties of null (reading 'value'), "
                "triggering the alert ('कृपया योग्य मोबाईल क्रमांक भरा!') or halting form postback execution."
            )
        else:
            classification = "E. INCONCLUSIVE"
            explanation = "Could not pinpoint missing DOM fields in validateMobileNumber()."

        print("\n==================================================")
        print("ROOT-CAUSE CLASSIFICATION SUMMARY")
        print("==================================================")
        print(f"Classification: {classification}")
        print(f"Explanation:    {explanation}")

        # Save Report JSON
        report = {
            "timestamp": datetime.now().isoformat(),
            "js_analysis": js_analysis,
            "record_type_info": rec_type_info,
            "buttons_info": buttons_info,
            "classification": classification,
            "explanation": explanation
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"submit_validation_investigation_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Investigation report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
