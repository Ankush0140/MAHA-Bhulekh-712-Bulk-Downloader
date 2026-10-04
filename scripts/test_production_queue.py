import asyncio
import os
import sys
import io
from pathlib import Path

# Force UTF-8 stdout for Devanagari characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.db import setup_database, Job, JobRecord
from app.models.location import LocationSelection
from app.services.db_service import create_job, upsert_discovered_records, update_job_status
from app.models.enums import JobStatus
from app.automation.browser import launch_browser_and_context
from playwright.async_api import async_playwright
from app.automation.worker import Worker

def print_queue_summary(db, job):
    print("\n" + "="*50)
    print("QUEUE EXECUTION SUMMARY")
    print("="*50)
    print(f"Job ID: {job.id}")
    print(f"Job Status: {job.status.name if hasattr(job.status, 'name') else str(job.status)}")
    print(f"Total Records: {job.total_records}")
    print(f"Completed Records: {job.completed_records}")
    print(f"Failed Records: {job.failed_records}")
    
    records = db.query(JobRecord).filter(JobRecord.job_id == job.id).all()
    for r in records:
        print(f"\n[{r.survey_identifier_original}]")
        print(f"  Status:  {r.status.name if hasattr(r.status, 'name') else str(r.status)}")
        print(f"  Attempt: {r.attempt_count}")
        if r.human_wait_seconds:
            print(f"  Human Wait: {r.human_wait_seconds:.2f}s")
        if r.automated_duration_seconds:
            print(f"  Auto Time:  {r.automated_duration_seconds:.2f}s")
        if r.output_relative_path:
            print(f"  Output: {r.output_relative_path}")
        if r.last_error_message:
            print(f"  Error: {r.last_error_code} - {r.last_error_message}")
    print("="*50 + "\n")

def get_user_choice(prompt: str, options: list) -> dict:
    print(f"\n{prompt}")
    for i, opt in enumerate(options, 1):
        print(f"[{i}] {opt['text']}")
    
    while True:
        try:
            choice = input(f"Select 1-{len(options)} (or 'q' to quit): ").strip()
            if choice.lower() == 'q':
                sys.exit(0)
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print("Invalid choice, please try again.")

async def main():
    print("=== BHULEKH BATCH QUEUE TESTER ===")
    
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / "app.db"
    output_dir = base_dir / "output"
    
    from app.automation.discovery import extract_select_options, is_placeholder_option, discover_numeric_surveys
    from app.automation.selectors import DISTRICT_SELECT, TALUKA_SELECT, VILLAGE_SELECT
    
    print("\nLaunching browser to fetch live location options...")
    
    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, headless=False)
        page = await context.new_page()
        
        await page.goto("https://bhulekh.mahabhumi.gov.in/", timeout=60000)
        await page.wait_for_load_state("domcontentloaded")
        
        # 1. District
        await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=10000)
        dist_opts = await extract_select_options(page, DISTRICT_SELECT)
        dist_opts = [o for o in dist_opts if not is_placeholder_option(o['text'], o['value'])]
        dist_choice = get_user_choice("Select District:", dist_opts)
        
        print(f"Selecting District: {dist_choice['text']}")
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await page.locator(DISTRICT_SELECT).select_option(value=dist_choice['value'])
        await page.wait_for_load_state("domcontentloaded")
        
        # 2. Taluka
        await page.wait_for_selector(TALUKA_SELECT, state="visible", timeout=10000)
        tal_opts = await extract_select_options(page, TALUKA_SELECT)
        tal_opts = [o for o in tal_opts if not is_placeholder_option(o['text'], o['value'])]
        tal_choice = get_user_choice("Select Taluka:", tal_opts)
        
        print(f"Selecting Taluka: {tal_choice['text']}")
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await page.locator(TALUKA_SELECT).select_option(value=tal_choice['value'])
        await page.wait_for_load_state("domcontentloaded")
        
        # 3. Village
        await page.wait_for_selector(VILLAGE_SELECT, state="visible", timeout=10000)
        vil_opts = await extract_select_options(page, VILLAGE_SELECT)
        vil_opts = [o for o in vil_opts if not is_placeholder_option(o['text'], o['value'])]
        vil_choice = get_user_choice("Select Village:", vil_opts)
        
        print(f"Selecting Village: {vil_choice['text']}")
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await page.locator(VILLAGE_SELECT).select_option(value=vil_choice['value'])
        await page.wait_for_load_state("domcontentloaded")
        
        # 4. Survey
        surveys_to_process = []
        while len(surveys_to_process) < 2:
            prefix = input(f"\nEnter a numeric prefix to search for survey {len(surveys_to_process)+1}/2 (e.g., 10, or '1' to see all 1s): ").strip()
            if not prefix: continue
            
            print(f"Discovering surveys for prefix '{prefix}'...")
            result = await discover_numeric_surveys(page, prefixes=[prefix], validate_completeness=False)
            if not result.records:
                print("No surveys found for this prefix. Try again.")
                continue
                
            opts = [{"text": r.display_text, "value": r.option_value} for r in result.records]
            choice = get_user_choice(f"Select Survey {len(surveys_to_process)+1}:", opts)
            
            if choice['text'] not in surveys_to_process:
                surveys_to_process.append(choice['text'])
            else:
                print("You already selected this survey. Pick another.")

        print("\n" + "="*50)
        print("LIVE TEST CONFIRMATION")
        print("="*50)
        print(f"District: {dist_choice['text']}")
        print(f"Taluka:   {tal_choice['text']}")
        print(f"Village:  {vil_choice['text']}\n")
        
        print(f"Record 1: {surveys_to_process[0]}")
        print(f"Record 2: {surveys_to_process[1]}\n")
        
        print(f"Records to process: 2")
        print("="*50)
        
        proceed = input("Continue? [y/N]: ").strip().lower()
        if proceed != 'y':
            print("Aborting.")
            return

        SessionLocal = setup_database(db_path)
        db = SessionLocal()
        
        loc = LocationSelection(
            district_text=dist_choice['text'], district_value=dist_choice['value'],
            taluka_text=tal_choice['text'], taluka_value=tal_choice['value'],
            village_text=vil_choice['text'], village_value=vil_choice['value'],
            division_text=None, division_value=None
        )
        job = create_job(db, loc)
        update_job_status(db, job.id, JobStatus.DISCOVERING)
        
        upsert_discovered_records(db, job.id, surveys_to_process)
        
        print(f"\n--- Starting Production Queue for Job ID {job.id} ---")
        print("WARNING: This will open an interactive Chrome window.")
        print("For each record, you MUST manually enter your mobile and the CAPTCHA in the BROWSER, then click Submit.")
        print("Do NOT enter them in this terminal.")
        
        worker = Worker(db, job.id, output_dir)
        await worker.run(page)
        
        await context.close()
        await browser.close()
        
        db.refresh(job)
        print_queue_summary(db, job)

if __name__ == "__main__":
    asyncio.run(main())
