import asyncio
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

async def inspect_districts():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            print("Navigating to Bhulekh portal...")
            await page.goto("https://bhulekh.mahabhumi.gov.in/")
            
            # Wait for District dropdown to be present and populated
            dropdown_selector = "#ContentPlaceHolder1_ddlMainDist"
            await page.wait_for_selector(dropdown_selector, state="visible", timeout=15000)
            
            # Wait a moment for any JS data-binding to finish (just in case)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)
            
            # Read options
            options = await page.eval_on_selector_all(
                f"{dropdown_selector} option",
                "elements => elements.map(el => ({text: el.innerText.trim(), value: el.value}))"
            )
            
            # Filter placeholders (usually value is '0', empty, or text contains 'Select' or 'निवडा')
            valid_options = []
            for opt in options:
                val = opt.get("value", "").strip()
                txt = opt.get("text", "").strip()
                if not val or val == "0" or "निवडा" in txt or "Select" in txt or "Select District" in txt or txt == "--- जिल्हा निवडा ---":
                    continue
                valid_options.append(opt)
                
            print("\nBHULEKH DISTRICT OPTION INSPECTION\n")
            print(f"TOTAL DISTRICT OPTIONS: {len(valid_options)}\n")
            
            for i, opt in enumerate(valid_options, 1):
                print(f"{i} | {opt['text']} | {opt['value']}")
                
        except Exception as e:
            print(f"Error during inspection: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect_districts())
