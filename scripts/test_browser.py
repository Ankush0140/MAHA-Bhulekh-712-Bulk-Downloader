import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"


async def main():
    print("==================================================")
    print("MAHA Bhulekh - System Chrome Verification Test")
    print("==================================================")
    print(f"Target URL: {PORTAL_URL}")
    print("Browser Channel: Google Chrome ('chrome')")
    print("Headless Mode: False")
    print("Launching browser...\n")

    async with async_playwright() as p:
        try:
            browser, context = await launch_browser_and_context(
                p, channel="chrome", headless=False
            )
            page = await context.new_page()

            print(f"Navigating to {PORTAL_URL} (timeout 60s)...")
            response = await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

            title = await page.title()
            current_url = page.url
            status = response.status if response else "Unknown"

            print("\n--------------------------------------------------")
            print("SUCCESS: Bhulekh Portal loaded successfully!")
            print(f"HTTP Status: {status}")
            print(f"Page Title: {title}")
            print(f"Current URL: {current_url}")
            print("--------------------------------------------------\n")

            # Pause for human verification
            await asyncio.get_event_loop().run_in_executor(
                None, input, "Press ENTER in this terminal to close the browser and exit script..."
            )

        except Exception as err:
            print("\n--------------------------------------------------")
            print("ERROR: Failed to launch browser or load Bhulekh Portal!")
            print(f"Details: {err}")
            print("--------------------------------------------------\n")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                print("Closing browser context cleanly...")
                await context.close()
                await browser.close()
                print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())
