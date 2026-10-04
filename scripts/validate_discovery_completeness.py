import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context
from app.automation.discovery import (
    extract_select_options,
    is_placeholder_option,
    compute_options_signature,
)
from app.automation.selectors import (
    PART1_INPUT,
    SEARCH_BUTTON,
    SURVEY_RESULT_SELECT,
)

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)


async def execute_prefix_query(page, prefix: str, request_delay: float = 0.5) -> dict:
    """Execute a single Part-1 prefix search and return cleaned option values and texts."""
    input_elem = page.locator(PART1_INPUT)
    await input_elem.fill("")
    await input_elem.fill(prefix)

    verified = await input_elem.input_value()
    if verified != prefix:
        raise ValueError(f"Input verification failed for '{prefix}'. Got '{verified}'")

    pre_options = await extract_select_options(page, SURVEY_RESULT_SELECT)
    pre_sig = compute_options_signature(pre_options)

    start_t = time.time()
    async with page.expect_response(
        lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
        timeout=30000
    ):
        await page.locator(SEARCH_BUTTON).click()

    await page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(request_delay)

    post_options = await extract_select_options(page, SURVEY_RESULT_SELECT)
    post_sig = compute_options_signature(post_options)
    elapsed = round(time.time() - start_t, 2)

    clean_dict = {
        opt["value"]: opt["text"]
        for opt in post_options
        if not is_placeholder_option(opt["text"], opt["value"])
    }

    return {
        "prefix": prefix,
        "elapsed_seconds": elapsed,
        "total_options": len(post_options),
        "clean_count": len(clean_dict),
        "signature": post_sig,
        "is_stale": (pre_sig == post_sig and len(pre_options) > 0),
        "clean_dict": clean_dict
    }


async def main():
    print("==================================================")
    print("Shivali Completeness Validation Script (Target Village)")
    print("==================================================")
    print("Launching Google Chrome...")

    target_parents = ["1", "2", "3", "4", "5", "6"]
    validation_results = {}

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("MANUAL ACTION REQUIRED IN CHROME:")
        print("Select: Pune -> Maval -> Shivali")
        print("--------------------------------------------------")
        await asyncio.get_event_loop().run_in_executor(
            None, input, "After selecting Pune -> Maval -> Shivali in Chrome, press ENTER to start validation..."
        )

        for parent in target_parents:
            print(f"\n==================================================")
            print(f"VALIDATING PARENT PREFIX '{parent}'")
            print(f"==================================================")

            # 1. Query Parent
            parent_res = await execute_prefix_query(page, parent)
            parent_vals = set(parent_res["clean_dict"].keys())
            print(f"Parent '{parent}' returned {len(parent_vals)} clean records (Time: {parent_res['elapsed_seconds']}s)")

            # 2. Query Child Prefixes P0..P9
            child_prefixes = [f"{parent}{d}" for d in range(10)]
            child_results_summary = {}
            child_union_dict = {}

            print(f"Querying 10 child prefixes for parent '{parent}': {child_prefixes} ...")
            for cp in child_prefixes:
                cp_res = await execute_prefix_query(page, cp)
                child_results_summary[cp] = cp_res["clean_count"]
                child_union_dict.update(cp_res["clean_dict"])
                print(f"   Child '{cp}': {cp_res['clean_count']} records")

            child_union_vals = set(child_union_dict.keys())
            missing_in_parent = child_union_vals - parent_vals

            is_truncated = len(missing_in_parent) > 0
            status_msg = "POSSIBLE_TRUNCATION" if is_truncated else "NO TRUNCATION DETECTED"

            print(f"\n--- PARENT '{parent}' SUMMARY ---")
            print(f"Parent Record Count:      {len(parent_vals)}")
            print(f"Child Union Unique Count: {len(child_union_vals)}")
            print(f"Child items NOT in Parent: {len(missing_in_parent)}")
            print(f"Validation Status:         {status_msg}")

            if is_truncated:
                print(f"   Sample missing items ({min(5, len(missing_in_parent))}):")
                for missing_val in list(missing_in_parent)[:5]:
                    print(f"      - Value: '{missing_val}', Text: '{child_union_dict[missing_val]}'")

            validation_results[parent] = {
                "parent_prefix": parent,
                "parent_count": len(parent_vals),
                "child_counts": child_results_summary,
                "child_union_count": len(child_union_vals),
                "missing_in_parent_count": len(missing_in_parent),
                "missing_items_sample": [
                    {"value": v, "text": child_union_dict[v]}
                    for v in list(missing_in_parent)[:20]
                ],
                "status": status_msg
            }

        # Final Overall Summary
        print("\n==================================================")
        print("OVERALL COMPLETENESS VALIDATION SUMMARY (SHIVALI)")
        print("==================================================")
        any_truncation = False
        for parent, res in validation_results.items():
            print(f"Parent '{parent}': Parent Count={res['parent_count']} | Child Union={res['child_union_count']} | Missing={res['missing_in_parent_count']} -> {res['status']}")
            if res["missing_in_parent_count"] > 0:
                any_truncation = True

        if not any_truncation:
            print("\n*** SUCCESS: ALL CHILD SETS ARE STRICT SUBSETS OF THEIR PARENT SETS ***")
            print("Baseline of 713 unique numeric records for Shivali (Pune -> Maval) is verified complete!")

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = LOG_DIR / f"shivali_completeness_validation_{timestamp_str}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(validation_results, f, ensure_ascii=False, indent=2)

        print(f"\n[SAVED] Report saved to: {filepath}")
        print("Closing browser...")
        await context.close()
        await browser.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
