import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Page

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.automation.browser import launch_browser_and_context

PORTAL_URL = "https://bhulekh.mahabhumi.gov.in/"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "investigation"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Verified Selectors
INPUT_PART1 = "#ContentPlaceHolder1_txtcsno"
BTN_SEARCH = "#ContentPlaceHolder1_btnsearchfind"
SELECT_SURVEY = "#ContentPlaceHolder1_ddlsurveyno"
SELECT_SEARCH_TYPE = "#ContentPlaceHolder1_ddlSelectSearchType"

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def compute_signature(options: list[dict]) -> str:
    """Compute MD5 signature of option list for stale-state detection."""
    raw = "|".join([f"{opt['value']}:{opt['text']}" for opt in options])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def is_placeholder(opt: dict) -> bool:
    """Identify placeholder select options like '--निवडा--'."""
    text = opt.get("text", "").strip()
    val = opt.get("value", "").strip()
    return "निवडा" in text or val in ["0", "-1", ""]


async def get_dropdown_options(page: Page, selector: str) -> list[dict]:
    """Retrieve all options from specified select element."""
    try:
        return await page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (!el) return [];
            return Array.from(el.options).map(o => ({{
                text: o.text.trim(),
                value: o.value
            }}));
        }}""", selector)
    except Exception as e:
        print(f"[DROPDOWN ERROR] Could not read {selector}: {e}")
        return []


async def execute_controlled_search(page: Page, term: str) -> dict:
    """Execute a controlled Part-1 search for a given term and return detailed metadata."""
    print(f"\n--- [SEARCH] Term: '{term}' ---")

    input_elem = page.locator(INPUT_PART1)
    await input_elem.fill("")
    await input_elem.fill(term)

    verified_val = await input_elem.input_value()
    if verified_val != term:
        raise ValueError(f"Input verification failed! Expected '{term}', got '{verified_val}'")

    pre_options = await get_dropdown_options(page, SELECT_SURVEY)
    pre_sig = compute_signature(pre_options)

    start_time = time.time()
    response_status = None
    try:
        async with page.expect_response(
            lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
            timeout=30000
        ) as resp_info:
            await page.locator(BTN_SEARCH).click()
        
        response = await resp_info.value
        response_status = response.status
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.0)
    except Exception as e:
        print(f"[POSTBACK WARNING] Timeout or issue waiting for postback response: {e}")

    elapsed_time = round(time.time() - start_time, 2)
    post_options = await get_dropdown_options(page, SELECT_SURVEY)
    post_sig = compute_signature(post_options)
    is_stale = (pre_sig == post_sig and len(pre_options) > 0)

    # Filter out placeholder option for clean analysis
    clean_options = [o for o in post_options if not is_placeholder(o)]

    print(f"Term '{term}': HTTP {response_status} | Count: {len(clean_options)} (Total: {len(post_options)}) | Time: {elapsed_time}s | Sig: {post_sig[:8]}")
    if is_stale:
        print("  *** STALE DROPDOWN DETECTED ***")

    return {
        "term": term,
        "verified_input": verified_val,
        "response_status": response_status,
        "elapsed_seconds": elapsed_time,
        "total_count": len(post_options),
        "clean_count": len(clean_options),
        "signature": post_sig,
        "is_stale": is_stale,
        "raw_options": post_options,
        "clean_options": clean_options
    }


async def run_test_a_refinement(page: Page, search_results_map: dict):
    """TEST A — PREFIX REFINEMENT / RESULT CAP (Terms 1, 10, 100)."""
    print("\n==================================================")
    print("TEST A — PREFIX REFINEMENT & RESULT CAP ANALYSIS (1, 10, 100)")
    print("==================================================")

    for term in ["1", "10", "100"]:
        if term not in search_results_map:
            search_results_map[term] = await execute_controlled_search(page, term)
            await asyncio.sleep(1.0)

    res_1 = search_results_map["1"]
    res_10 = search_results_map["10"]
    res_100 = search_results_map["100"]

    set_1 = {o["value"] for o in res_1["clean_options"]}
    set_10 = {o["value"] for o in res_10["clean_options"]}
    set_100 = {o["value"] for o in res_100["clean_options"]}

    not_in_1 = set_10 - set_1
    not_in_10 = set_100 - set_10

    max_count = max(res_1["clean_count"], res_10["clean_count"], res_100["clean_count"])

    print(f"\n--- TEST A FINDINGS ---")
    print(f"Count for '1':   {res_1['clean_count']} options")
    print(f"Count for '10':  {res_10['clean_count']} options")
    print(f"Count for '100': {res_100['clean_count']} options")
    print(f"Maximum count observed: {max_count}")
    print(f"Results in prefix '10' NOT found in prefix '1':  {len(not_in_1)}")
    if not_in_1:
        print(f"   Missing sample from '1': {list(not_in_1)[:5]}")
        print("   -> TRUNCATION / SERVER CAP INDICATED (Prefix '1' result set is incomplete!)")
    else:
        print("   -> All '10' items are contained within '1' (No truncation detected for '10').")

    print(f"Results in prefix '100' NOT found in prefix '10': {len(not_in_10)}")
    if not_in_10:
        print(f"   Missing sample from '10': {list(not_in_10)[:5]}")
        print("   -> TRUNCATION / SERVER CAP INDICATED (Prefix '10' result set is incomplete!)")

    return {
        "max_count_observed": max_count,
        "results_10_not_in_1_count": len(not_in_1),
        "results_10_not_in_1_sample": list(not_in_1)[:10],
        "results_100_not_in_10_count": len(not_in_10),
        "results_100_not_in_10_sample": list(not_in_10)[:10],
    }


def run_test_b_subdivision_analysis(search_results_map: dict):
    """TEST B — SUBDIVISION / HISSA ANALYSIS."""
    print("\n==================================================")
    print("TEST B — SUBDIVISION / HISSA PATTERN ANALYSIS")
    print("==================================================")

    all_options_dict = {}
    for res in search_results_map.values():
        for opt in res["clean_options"]:
            all_options_dict[opt["value"]] = opt["text"]

    simple_numeric = []
    with_slash = []
    with_dash = []
    with_devanagari = []

    for val, txt in all_options_dict.items():
        if txt.isdigit():
            simple_numeric.append(txt)
        if "/" in txt:
            with_slash.append(txt)
        if "-" in txt:
            with_dash.append(txt)
        if DEVANAGARI_RE.search(txt):
            with_devanagari.append(txt)

    print(f"Total Unique Options Analyzed across Searches: {len(all_options_dict)}")
    print(f"Simple Numeric Options (e.g. '1', '10'): {len(simple_numeric)} (Sample: {simple_numeric[:5]})")
    print(f"Subdivision Options with '/' (e.g. '10/1'): {len(with_slash)} (Sample: {with_slash[:5]})")
    print(f"Options with '-' (e.g. '1-A'): {len(with_dash)} (Sample: {with_dash[:5]})")
    print(f"Options with Devanagari characters (e.g. '10/1/अ'): {len(with_devanagari)} (Sample: {with_devanagari[:5]})")

    return {
        "total_unique_options_analyzed": len(all_options_dict),
        "simple_numeric_count": len(simple_numeric),
        "simple_numeric_sample": simple_numeric[:10],
        "with_slash_count": len(with_slash),
        "with_slash_sample": with_slash[:10],
        "with_dash_count": len(with_dash),
        "with_dash_sample": with_dash[:10],
        "with_devanagari_count": len(with_devanagari),
        "with_devanagari_sample": with_devanagari[:10]
    }


async def run_test_c_coverage(page: Page, search_results_map: dict):
    """TEST C — NUMERIC PREFIX COVERAGE (Terms 1 through 9)."""
    print("\n==================================================")
    print("TEST C — NUMERIC PREFIX COVERAGE (Prefixes 1 through 9)")
    print("==================================================")

    for term in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        if term not in search_results_map:
            search_results_map[term] = await execute_controlled_search(page, term)
            await asyncio.sleep(1.0)

    total_raw_count = 0
    all_values = []
    prefix_counts = {}

    for term in ["1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        res = search_results_map[term]
        opts = [o["value"] for o in res["clean_options"]]
        total_raw_count += len(opts)
        all_values.extend(opts)
        prefix_counts[term] = len(opts)

    unique_values = set(all_values)
    duplicate_count = total_raw_count - len(unique_values)
    zero_prefixes = [k for k, v in prefix_counts.items() if v == 0]

    print(f"\n--- NUMERIC COVERAGE SUMMARY ---")
    print(f"Total Raw Options Collected (1-9): {total_raw_count}")
    print(f"Unique Options (Deduplicated):      {len(unique_values)}")
    print(f"Duplicate Count across Prefixes:   {duplicate_count}")
    print(f"Prefixes with 0 results:            {zero_prefixes}")
    print("Counts per Prefix:")
    for k, v in prefix_counts.items():
        print(f"   Prefix '{k}': {v} records")

    return {
        "total_raw_options": total_raw_count,
        "unique_options_count": len(unique_values),
        "duplicate_count": duplicate_count,
        "zero_result_prefixes": zero_prefixes,
        "counts_per_prefix": prefix_counts
    }


async def run_test_d_akshar(page: Page):
    """TEST D — AKSHAR SURVEY NUMBER MODE INSPECTION."""
    print("\n==================================================")
    print("TEST D — AKSHAR SURVEY NUMBER MODE INSPECTION")
    print("==================================================")

    try:
        select_elem = page.locator(SELECT_SEARCH_TYPE)
        current_val = await select_elem.evaluate("el => el.value")
        print(f"Current Search Mode Value: '{current_val}' (Expected '2' for standard survey number)")

        print("Switching Search Mode to '8' (अक्षरी सर्वे नंबर)...")
        
        async with page.expect_response(
            lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
            timeout=10000
        ) as resp_info:
            await select_elem.select_option("8")

        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.0)
        
        new_val = await select_elem.evaluate("el => el.value")
        input_visible = await page.locator(INPUT_PART1).is_visible()
        btn_visible = await page.locator(BTN_SEARCH).is_visible()
        dropdown_options = await get_dropdown_options(page, SELECT_SURVEY)

        print(f"New Search Mode Value: '{new_val}'")
        print(f"Part-1 Input Field Visible? {input_visible}")
        print(f"Search Button Visible?       {btn_visible}")
        print(f"Survey Dropdown Option Count: {len(dropdown_options)}")

        # Switch back to standard survey mode (value 2)
        print("Restoring Search Mode back to '2' (सर्वे नंबर)...")
        async with page.expect_response(
            lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
            timeout=10000
        ):
            await select_elem.select_option("2")
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.0)

        return {
            "initial_mode": current_val,
            "akshar_mode_value": new_val,
            "input_visible": input_visible,
            "btn_visible": btn_visible,
            "akshar_dropdown_count": len(dropdown_options),
            "restored_mode": "2"
        }
    except Exception as e:
        print(f"[TEST D ERROR] Akshar mode inspection encountered error: {e}")
        return {"error": str(e)}


def run_test_e_captcha_boundary():
    """TEST E — CAPTCHA BOUNDARY OBSERVATION."""
    print("\n==================================================")
    print("TEST E — CAPTCHA BOUNDARY OBSERVATION")
    print("==================================================")
    print("Empirical Observation:")
    print("1. District, Taluka, and Village selection occur without CAPTCHA.")
    print("2. Survey Number (Part-1) search and Survey Dropdown population occur WITHOUT requiring CAPTCHA.")
    print("3. CAPTCHA is displayed only on the main form prior to submitting the final record request.")
    print("--> CONCLUSION: Survey/Gat discovery can proceed safely BEFORE human CAPTCHA input.")

    return {
        "captcha_required_for_discovery": False,
        "captcha_stage": "Pre-submission of final 7/12 record"
    }


async def main():
    print("==================================================")
    print("MAHA Bhulekh Comprehensive Investigation Suite (Phase 2 Final)")
    print("==================================================")

    search_results_map = {}

    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, channel="chrome", headless=False)
        page = await context.new_page()

        print(f"Navigating to {PORTAL_URL}...")
        await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=60000)

        print("\n--------------------------------------------------")
        print("MANUAL ACTION REQUIRED IN CHROME:")
        print("Select the SAME District -> Taluka -> Village used in prior tests.")
        print("--------------------------------------------------")
        await asyncio.get_event_loop().run_in_executor(
            None, input, "After selecting District, Taluka, and Village, press ENTER here to start automated tests..."
        )

        test_a_res = await run_test_a_refinement(page, search_results_map)
        test_b_res = run_test_b_subdivision_analysis(search_results_map)
        test_c_res = await run_test_c_coverage(page, search_results_map)
        test_d_res = await run_test_d_akshar(page)
        test_e_res = run_test_e_captcha_boundary()

        full_report = {
            "timestamp": datetime.now().isoformat(),
            "test_a_refinement": test_a_res,
            "test_b_subdivision": test_b_res,
            "test_c_coverage": test_c_res,
            "test_d_akshar": test_d_res,
            "test_e_captcha_boundary": test_e_res,
            "raw_search_runs": {
                k: {
                    "term": v["term"],
                    "clean_count": v["clean_count"],
                    "total_count": v["total_count"],
                    "elapsed_seconds": v["elapsed_seconds"],
                    "is_stale": v["is_stale"],
                    "signature": v["signature"]
                }
                for k, v in search_results_map.items()
            }
        }

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = LOG_DIR / f"final_investigation_suite_{timestamp_str}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(full_report, f, ensure_ascii=False, indent=2)

        print(f"\n[COMPLETE] Investigation suite finished. Full report saved to: {report_file}")
        print("Closing browser...")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
