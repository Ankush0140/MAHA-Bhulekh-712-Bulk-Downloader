import asyncio
import os
import sys
import io
from pathlib import Path

# Force UTF-8 stdout for Devanagari characters
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add project root to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.db import setup_database
from app.models.location import LocationSelection
from app.services.db_service import create_job, upsert_discovered_records, update_job_status
from app.models.enums import JobStatus
from app.automation.browser import launch_browser_and_context
from playwright.async_api import async_playwright
from app.automation.worker import Worker

def print_job_summary(db, job):
    print("\n--- Final Results ---")
    print(f"Job ID: {job.id}")
    print(f"Job Status: {job.status.name if hasattr(job.status, 'name') else str(job.status)}")
    print(f"Total Records: {job.total_records}")
    print(f"Completed Records: {job.completed_records}")
    print(f"Failed Records: {job.failed_records}")
    print(f"Remaining Records: {job.total_records - (job.completed_records + job.failed_records + job.empty_records)}")
    
    from app.models.db import JobRecord
    from app.services.db_service import verify_output_pdf
    
    base_dir = Path(__file__).resolve().parent.parent
    records = db.query(JobRecord).filter(JobRecord.job_id == job.id).all()
    
    for r in records:
        print(f"\nRecord original identifier: {r.survey_identifier_original}")
        print(f"Record status: {r.status.name if hasattr(r.status, 'name') else str(r.status)}")
        auto_time = f"{r.automated_duration_seconds:.2f}s" if r.automated_duration_seconds else "N/A"
        human_time = f"{r.human_wait_seconds:.2f}s" if r.human_wait_seconds else "N/A"
        print(f"Human wait seconds: {human_time}")
        print(f"Automated duration seconds: {auto_time}")
        print(f"Output relative path: {r.output_relative_path}")
        
        pdf_valid = False
        if r.output_relative_path:
            full_path = base_dir / "output" / r.output_relative_path
            pdf_valid = verify_output_pdf(full_path)
        print(f"PDF validation result: {'PASS' if pdf_valid else 'FAIL'}")
        
        if r.last_error_message:
            print(f"Error: {r.last_error_code} - {r.last_error_message}")

async def main():
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / "app.db"
    output_dir = base_dir / "output"
    
    SessionLocal = setup_database(db_path)
    db = SessionLocal()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        job_id = int(sys.argv[2])
        from app.models.db import Job
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            print_job_summary(db, job)
        else:
            print(f"Job {job_id} not found.")
        return

    # 1. Create temporary job with verified real location
    loc = LocationSelection(
        district_text="यवतमाळ", district_value="14",
        taluka_text="कळंब", taluka_value="3",
        village_text="आमला", village_value="271400030172280000",
        division_text=None, division_value=None
    )
    job = create_job(db, loc)
    update_job_status(db, job.id, JobStatus.DISCOVERING)
    
    # 2. Persist ONE actual Survey/Gat record
    survey_identifier = "30/2/अ"
    upsert_discovered_records(db, job.id, [survey_identifier])
    
    # 3. Worker opens Chrome
    print(f"\n--- Starting Production Worker for Job ID {job.id} ---")
    print(f"Location: {loc.district_text} -> {loc.taluka_text} -> {loc.village_text}")
    print(f"Target Record: {survey_identifier}")
    print("WARNING: This will open an interactive Chrome window.")
    print("You MUST manually enter your mobile and the CAPTCHA, then click Submit.")
    
    async with async_playwright() as p:
        browser, context = await launch_browser_and_context(p, headless=False)
        page = await context.new_page()
        
        worker = Worker(db, job.id, output_dir)
        await worker.run(page)
        
        await context.close()
        await browser.close()
        
    db.refresh(job)
    print_job_summary(db, job)

if __name__ == "__main__":
    asyncio.run(main())
