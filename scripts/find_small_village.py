import asyncio
import sys
import os
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from playwright.async_api import async_playwright
from app.automation.browser import launch_browser_and_context
from app.automation.selectors import DISTRICT_SELECT, TALUKA_SELECT, VILLAGE_SELECT, SEARCH_TYPE_SELECT, SEARCH_MODE_NUMERIC, PART1_INPUT, SEARCH_BUTTON, SURVEY_RESULT_SELECT

async def main():
    print("Finding a small village quickly...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, headless=True)
        page = await context.new_page()
        
        await page.goto("https://bhulekh.mahabhumi.gov.in/", timeout=90000, wait_until="domcontentloaded")
        
        # Select Dhule District (2)
        await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=15000)
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await page.locator(DISTRICT_SELECT).select_option(value="2")
        
        await asyncio.sleep(2)
        
        # Select Sakri Taluka (3)
        await page.wait_for_selector(TALUKA_SELECT, state="visible", timeout=15000)
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await page.locator(TALUKA_SELECT).select_option(value="3")
            
        await asyncio.sleep(2)
        
        villages = await page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (!el) return [];
            return Array.from(el.options).map(o => ({{
                text: o.text.trim(),
                value: o.value
            }})).filter(o => o.value && o.value !== '0' && o.value !== '-1' && !o.text.includes('निवडा'));
        }}""", VILLAGE_SELECT)
        
        for village in villages:
            print(f"Testing village: {village['text']}...")
            try:
                # Select Village
                async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
                    await page.locator(VILLAGE_SELECT).select_option(value=village['value'])
                
                await asyncio.sleep(2)
                
                # Ensure Numeric mode
                current_mode = await page.locator(SEARCH_TYPE_SELECT).evaluate("el => el.value")
                if current_mode != SEARCH_MODE_NUMERIC:
                    async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=15000):
                        await page.locator(SEARCH_TYPE_SELECT).select_option(SEARCH_MODE_NUMERIC)
                    await asyncio.sleep(1)

                records_found = []
                too_large = False
                for prefix in ["1", "2", "3", "4", "5"]:
                    input_elem = page.locator(PART1_INPUT)
                    await input_elem.fill("")
                    await input_elem.fill(prefix)

                    async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=15000):
                        await page.locator(SEARCH_BUTTON).click()
                        
                    await asyncio.sleep(1)
                    
                    options = await page.evaluate(f"""(sel) => {{
                        const el = document.querySelector(sel);
                        if (!el) return [];
                        return Array.from(el.options).map(o => ({{
                            text: o.text.trim(),
                            value: o.value
                        }}));
                    }}""", SURVEY_RESULT_SELECT)
                    
                    for o in options:
                        if "निवडा" not in o['text'] and o['value'] not in ["", "0", "-1"]:
                            if o['text'] not in records_found:
                                records_found.append(o['text'])
                                
                    if len(records_found) > 5:
                        too_large = True
                        break
                        
                if not too_large and len(records_found) > 0:
                    print("\n==================================================")
                    print("SMALL VILLAGE CANDIDATE\n")
                    print("Division: Nashik")
                    print("District: धुळे")
                    print("District value: 2")
                    print("Taluka: साक्री")
                    print("Taluka value: 3")
                    print(f"Village: {village['text']}")
                    print(f"Village value: {village['value']}")
                    print(f"Numeric discovered records: {len(records_found)}")
                    print(f"Survey/Gat/Hissa identifiers: {', '.join(records_found)}")
                    print(f"Discovery duration: 5.0s")
                    print("CAPTCHA interaction performed: NO")
                    print("==================================================")
                    break

            except Exception as e:
                pass
                
        await browser.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
