import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.automation.discovery import discover_numeric_surveys

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def on_prefix_progress(prefix: str, valid_count: int, total_unique_so_far: int):
    print(f"Searching prefix {prefix}/9 ... {valid_count} records found (Total unique so far: {total_unique_so_far})")


async def main():
    print("==================================================")
    print("MAHA Bhulekh Phase 3 Production Discovery Smoke Test")
    print("==================================================")
    print("Launching Google Chrome...")

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("MANUAL ACTION REQUIRED IN CHROME:")
        print("Select District -> Taluka -> Village (e.g. अमरावती -> अमरावती -> अंभोळा)")
        print("--------------------------------------------------")
        await asyncio.get_event_loop().run_in_executor(
            None, input, "After selecting District, Taluka, and Village, press ENTER here to start production discovery..."
        )

        print("\nExecuting production numeric discovery across prefixes 1 to 9...\n")
        discovery_result = await discover_numeric_surveys(
            page,
            prefixes=["1", "2", "3", "4", "5", "6", "7", "8", "9"],
            request_delay=0.5,
            validate_completeness=True,
            on_progress=on_prefix_progress
        )

        print("\n==================================================")
        print("DISCOVERY COMPLETED SUMMARY")
        print("==================================================")
        print("Prefix Counts:")
        for prefix, count in discovery_result.prefix_counts.items():
            print(f"  Prefix '{prefix}': {count} records")

        print(f"\nTotal Unique Records Discovered: {discovery_result.total_unique}")
        print(f"Duplicates Removed:             {discovery_result.duplicates_removed}")
        print(f"Failed Prefixes:                {discovery_result.failed_prefixes}")
        print(f"Warnings:                       {discovery_result.warnings}")
        print(f"Elapsed Discovery Time:        {discovery_result.elapsed_seconds} seconds")

        if discovery_result.records:
            print("\nFirst 5 Representative Records:")
            for rec in discovery_result.records[:5]:
                print(f"  - [{rec.discovery_order}] Text: '{rec.display_text}', Value: '{rec.option_value}' (Prefix: {rec.source_prefix})")

            print("\nLast 5 Representative Records:")
            for rec in discovery_result.records[-5:]:
                print(f"  - [{rec.discovery_order}] Text: '{rec.display_text}', Value: '{rec.option_value}' (Prefix: {rec.source_prefix})")

        # Regression check note for test village (expected ~928 unique)
        EXPECTED_TEST_VILLAGE_BASELINE = 928
        if discovery_result.total_unique == EXPECTED_TEST_VILLAGE_BASELINE:
            print(f"\n[REGRESSION SANITY CHECK] SUCCESS: Matched expected baseline of {EXPECTED_TEST_VILLAGE_BASELINE} unique records!")
        else:
            print(f"\n[REGRESSION SANITY CHECK] Note: Returned {discovery_result.total_unique} unique records (Baseline for test village: {EXPECTED_TEST_VILLAGE_BASELINE}).")

        # Save result JSON
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "total_unique": discovery_result.total_unique,
            "duplicates_removed": discovery_result.duplicates_removed,
            "prefix_counts": discovery_result.prefix_counts,
            "failed_prefixes": discovery_result.failed_prefixes,
            "warnings": discovery_result.warnings,
            "elapsed_seconds": discovery_result.elapsed_seconds,
            "sample_records": [
                {
                    "order": r.discovery_order,
                    "text": r.display_text,
                    "value": r.option_value,
                    "prefix": r.source_prefix
                }
                for r in discovery_result.records[:20]
            ],
            "all_records": [
                {
                    "order": r.discovery_order,
                    "text": r.display_text,
                    "value": r.option_value,
                    "prefix": r.source_prefix
                }
                for r in discovery_result.records
            ]
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"discovery_smoketest_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Log file saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
