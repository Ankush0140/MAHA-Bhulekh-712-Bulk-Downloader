import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page, Request, Response

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

SENSITIVE_FIELD_PATTERNS = ["captcha", "mobile", "phone", "pass", "pwd", "token", "session", "cookie", "auth"]
captured_network_events = []


def is_sensitive(key_name: str) -> bool:
    name_lower = key_name.lower()
    return any(p in name_lower for p in SENSITIVE_FIELD_PATTERNS)


async def on_request(request: Request):
    try:
        url = request.url
        resource_type = request.resource_type
        # Filter relevant XHR / fetch / document requests from Bhulekh portal
        if resource_type in ["xhr", "fetch", "document"] and "mahabhumi.gov.in" in url:
            method = request.method
            headers = {
                k: ("[REDACTED]" if is_sensitive(k) else v)
                for k, v in request.headers.items()
            }
            
            post_data = None
            if request.post_data:
                try:
                    # Attempt to parse json or post body
                    data = json.loads(request.post_data)
                    post_data = {
                        k: ("[REDACTED]" if is_sensitive(k) else v)
                        for k, v in data.items()
                    } if isinstance(data, dict) else "[REDACTED_POST_DATA]"
                except Exception:
                    post_data = "[NON_JSON_POST_DATA]"

            event = {
                "timestamp": datetime.now().isoformat(),
                "event": "request",
                "method": method,
                "url": url,
                "resource_type": resource_type,
                "headers": headers,
                "post_data": post_data,
            }
            captured_network_events.append(event)
            print(f"\n[NETWORK REQ] {method} {url} ({resource_type})")
    except Exception as e:
        print(f"[LOG ERROR] {e}")


async def on_response(response: Response):
    try:
        url = response.url
        request = response.request
        resource_type = request.resource_type
        if resource_type in ["xhr", "fetch", "document"] and "mahabhumi.gov.in" in url:
            status = response.status
            content_type = response.headers.get("content-type", "")
            
            event = {
                "timestamp": datetime.now().isoformat(),
                "event": "response",
                "status": status,
                "url": url,
                "resource_type": resource_type,
                "content_type": content_type,
            }
            captured_network_events.append(event)
            print(f"[NETWORK RES] {status} {url} ({content_type})")
    except Exception as e:
        print(f"[LOG ERROR] {e}")


async def inspect_dom(page: Page) -> dict:
    """Inspect all SELECT, INPUT, and BUTTON controls on the current page."""
    dom_summary = await page.evaluate("""() => {
        const selects = Array.from(document.querySelectorAll('select')).map((el, index) => {
            const options = Array.from(el.options).map(o => ({
                text: o.text.trim(),
                value: o.value
            }));
            const selectedOpt = el.options[el.selectedIndex];
            return {
                index: index,
                id: el.id || null,
                name: el.name || null,
                ariaLabel: el.getAttribute('aria-label') || null,
                disabled: el.disabled,
                optionCount: options.length,
                selectedOption: selectedOpt ? { text: selectedOpt.text.trim(), value: selectedOpt.value } : null,
                sampleOptions: options.slice(0, 15)
            };
        });

        const inputs = Array.from(document.querySelectorAll('input')).map((el, index) => {
            const inputType = (el.type || 'text').toLowerCase();
            const isSensitive = ['password', 'hidden'].includes(inputType) || 
                                (el.name && /captcha|mobile|phone|token|pass/i.test(el.name)) ||
                                (el.id && /captcha|mobile|phone|token|pass/i.test(el.id));
            return {
                index: index,
                id: el.id || null,
                name: el.name || null,
                type: inputType,
                placeholder: el.placeholder || null,
                disabled: el.disabled,
                value: isSensitive ? '[REDACTED]' : el.value
            };
        });

        const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]')).map((el, index) => {
            return {
                index: index,
                id: el.id || null,
                name: el.name || null,
                type: el.type || 'button',
                text: el.innerText ? el.innerText.trim() : el.value || null,
                disabled: el.disabled
            };
        });

        return {
            title: document.title,
            url: window.location.href,
            selects: selects,
            inputs: inputs,
            buttons: buttons
        };
    }""")

    return dom_summary


def display_dom_summary(dom: dict):
    print("\n==================================================")
    print(f"PAGE TITLE: {dom['title']}")
    print(f"PAGE URL:   {dom['url']}")
    print("==================================================")

    print(f"\n--- SELECT ELEMENTS ({len(dom['selects'])}) ---")
    for sel in dom['selects']:
        selected_txt = sel['selectedOption']['text'] if sel['selectedOption'] else 'None'
        print(f"[{sel['index']}] ID: '{sel['id']}' | Name: '{sel['name']}' | Options: {sel['optionCount']} | Selected: '{selected_txt}'")
        if sel['sampleOptions']:
            print("    First few options:")
            for opt in sel['sampleOptions'][:5]:
                print(f"      - value: '{opt['value']}', text: '{opt['text']}'")

    print(f"\n--- INPUT ELEMENTS ({len(dom['inputs'])}) ---")
    for inp in dom['inputs']:
        print(f"[{inp['index']}] ID: '{inp['id']}' | Name: '{inp['name']}' | Type: '{inp['type']}' | Placeholder: '{inp['placeholder']}'")

    print(f"\n--- BUTTON ELEMENTS ({len(dom['buttons'])}) ---")
    for btn in dom['buttons']:
        print(f"[{btn['index']}] ID: '{btn['id']}' | Name: '{btn['name']}' | Type: '{btn['type']}' | Text: '{btn['text']}'")
    print("==================================================\n")


async def save_investigation_log(dom: dict):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = LOG_DIR / f"portal_inspection_{timestamp}.json"
    data = {
        "timestamp": timestamp,
        "dom_summary": dom,
        "network_events": captured_network_events
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVED] Investigation log saved to: {filepath}")


async def interactive_loop(page: Page):
    while True:
        print("\n--- INTERACTIVE PORTAL INSPECTOR ---")
        print("Perform manual interactions in Chrome (e.g. select District, Taluka, Village, etc.)")
        print("[1] Inspect current DOM & Form Controls")
        print("[2] View recent XHR/Fetch network events")
        print("[3] Save current snapshot & logs to file")
        print("[q] Quit and close browser")
        
        choice = await asyncio.get_event_loop().run_in_executor(
            None, input, "Enter option (1/2/3/q): "
        )
        choice = choice.strip().lower()

        if choice == "1":
            dom = await inspect_dom(page)
            display_dom_summary(dom)
        elif choice == "2":
            print(f"\n--- CAPTURED NETWORK EVENTS ({len(captured_network_events)}) ---")
            for ev in captured_network_events[-10:]:
                print(f"[{ev['timestamp']}] {ev['event'].upper()} {ev.get('method', ev.get('status'))} {ev['url']}")
        elif choice == "3":
            dom = await inspect_dom(page)
            await save_investigation_log(dom)
        elif choice == "q":
            print("Exiting inspector...")
            break
        else:
            print("Invalid option. Enter 1, 2, 3, or q.")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Portal Inspection Script (Phase 2A)")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        # Attach network listeners
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("Page loaded. Starting interactive inspector session.")
        await interactive_loop(page)

        print("Closing browser context...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
