import asyncio
import time
from pathlib import Path
from app.dependencies import SessionLocal
from playwright.async_api import Page

from app.models.db import Job, JobRecord
from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.services.db_service import (
    get_job, get_next_pending_record, 
    mark_record_waiting_for_captcha, mark_record_running,
    mark_record_completed, mark_record_failed, update_job_status
)
from app.automation.navigation import (
    select_location, prepare_record, wait_for_human_result, 
    NavigationError, HumanWaitTimeout, PauseRequested, SessionResetDetected,
    InvisibleWindowError
)
from app.automation.record_capture import extract_record_image, save_record_pdf, ImageCaptureError
from app.services.filename import build_output_filepath
from app.models.location import LocationSelection

from app.automation.retry import (
    MAX_ATTEMPTS, is_retryable_error, is_human_session_error, 
    apply_backoff, apply_rate_limit
)
from app.services.db_service import verify_output_pdf, mark_record_attempt_started
import logging

# Set up structured logger
logger = logging.getLogger(__name__)

class Worker:
    def __init__(self, job_id: int, base_output_dir: Path):
        self.job_id = job_id
        self.base_output_dir = Path(base_output_dir)

    async def run(self, page: Page):
        """Main loop for processing a job's records."""
        with SessionLocal() as db:
            job = get_job(db, self.job_id)
            if not job or job.status not in [JobStatus.DISCOVERING, JobStatus.RUNNING, JobStatus.WAITING_FOR_CAPTCHA]:
                return
                
            update_job_status(db, self.job_id, JobStatus.RUNNING)

        while True:
            # Refresh job state
            with SessionLocal() as db:
                job = get_job(db, self.job_id)
                if job.pause_requested:
                    update_job_status(db, self.job_id, JobStatus.PAUSED)
                    break
                    
                record = get_next_pending_record(db, self.job_id)
                if not record:
                    break 
                    
            # process_record manages its own db sessions internally
            await self.process_record(page)
            
            # Rate limit before next record
            await apply_rate_limit()
            
        with SessionLocal() as db:
            job = get_job(db, self.job_id)
            if job and job.status in [JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED]:
                from app.services.report import generate_job_reports
                generate_job_reports(db, self.job_id, self.base_output_dir)
            
    async def process_record(self, page: Page):
        automated_start = time.time()
        human_wait_start = None
        human_wait_duration = 0.0
        
        with SessionLocal() as db:
            job = get_job(db, self.job_id)
            record = get_next_pending_record(db, self.job_id)
            if not record:
                return
            loc = LocationSelection(
                division_text=job.division_text, division_value=job.division_value,
                district_text=job.district_text, district_value=job.district_value,
                taluka_text=job.taluka_text, taluka_value=job.taluka_value,
                village_text=job.village_text, village_value=job.village_value
            )
            record_id = record.id
            record_survey_identifier = record.survey_identifier_original
            job_id_val = job.id
            
        output_path = build_output_filepath(loc, record_survey_identifier, self.base_output_dir)
        
        if verify_output_pdf(output_path):
            logger.info({"msg": "Idempotent skip, valid PDF already exists", "job_id": job_id_val, "record_id": record_id})
            rel_path = output_path.relative_to(self.base_output_dir).as_posix()
            with SessionLocal() as db:
                mark_record_completed(db, record_id, output_relative_path=rel_path, pdf_size_bytes=output_path.stat().st_size)
            return

        for attempt in range(1, MAX_ATTEMPTS + 1):
            with SessionLocal() as db:
                mark_record_attempt_started(db, record_id)
            try:
                # Safe recovery to entry state
                await page.goto("https://bhulekh.mahabhumi.gov.in/", timeout=60000)
                await page.wait_for_load_state("domcontentloaded")
                
                await select_location(page, loc) # Note: select_location expects a Job or LocationSelection, using loc which is equivalent
                await prepare_record(page, record_survey_identifier, job_id_val, record_id)
                
                with SessionLocal() as db:
                    mark_record_waiting_for_captcha(db, record_id)
                    update_job_status(db, self.job_id, JobStatus.WAITING_FOR_CAPTCHA)
                
                # Surface the official page for the operator (no field interaction).
                try:
                    await page.bring_to_front()
                except Exception:
                    pass
                
                target_title = f"BHULEKH_JOB_{job_id_val}_RECORD_{record_id}_WAITING"
                try:
                    await page.evaluate(f'document.title = "{target_title}"')
                except Exception:
                    pass
                
                human_wait_start = time.time()
                
                # Wait for Human
                try:
                    await wait_for_human_result(page, self.job_id, timeout_ms=3600000, target_title=target_title)
                except HumanWaitTimeout:
                    logger.info({"msg": "Human wait timeout", "job_id": job_id_val, "record_id": record_id})
                    # Do not fail record, do not retry. Just pause the job.
                    with SessionLocal() as db:
                        job = get_job(db, self.job_id)
                        if job:
                            job.pause_requested = True
                            db.commit()
                    return # Exit this record processing, outer loop will see pause
                except PauseRequested:
                    logger.info({"msg": "Pause detected during human wait", "job_id": job_id_val, "record_id": record_id})
                    return # Exit this record processing, outer loop will see pause
                except SessionResetDetected:
                    logger.info({"msg": "Session reset detected during human wait", "job_id": job_id_val, "record_id": record_id})
                    # Exit this attempt so that the outer queue loop will fetch it again (as it's still WAITING_FOR_CAPTCHA)
                    # and start a fresh automation prep cycle.
                    return
                except InvisibleWindowError as e:
                    logger.error({"msg": "Window invisibility detected", "job_id": job_id_val, "record_id": record_id})
                    # Do not fail the record for environmental UI issues. Pause the job safely.
                    with SessionLocal() as db:
                        job = get_job(db, self.job_id)
                        if job:
                            job.pause_requested = True
                            job.last_error_message = "Paused: Human verification window is invisible or isolated."
                            db.commit()
                    return
                finally:
                    duration = time.time() - human_wait_start
                    human_wait_duration += duration
                    with SessionLocal() as db:
                        r = db.query(JobRecord).filter(JobRecord.id == record_id).first()
                        if r:
                            r.human_wait_seconds = (r.human_wait_seconds or 0) + duration
                            db.commit()
                        
                with SessionLocal() as db:
                    mark_record_running(db, record_id)
                    update_job_status(db, self.job_id, JobStatus.RUNNING)
                
                # Capture Image Bytes
                try:
                    rec_image = await extract_record_image(page)
                except ImageCaptureError as ice:
                    raise NavigationError(f"Capture failed: {ice}", ErrorCategory.CAPTURE_ERROR)
                
                capture_res = save_record_pdf(rec_image, output_path)
                if not capture_res.created:
                    raise NavigationError(capture_res.error_message or "PDF write failed", ErrorCategory.PDF_WRITE_ERROR)
                    
                rel_path = output_path.relative_to(self.base_output_dir).as_posix()
                
                # Complete
                # Complete
                with SessionLocal() as db:
                    mark_record_completed(db, record_id, output_relative_path=rel_path, pdf_size_bytes=capture_res.size_bytes)
                break # Success, exit retry loop
                
            except NavigationError as ne:
                logger.error({"msg": "Navigation error", "job_id": job_id_val, "record_id": record_id, "attempt": attempt, "category": ne.category.value, "error": str(ne)})
                
                if is_retryable_error(ne.category):
                    if attempt < MAX_ATTEMPTS:
                        await apply_backoff(attempt)
                        continue
                    else:
                        with SessionLocal() as db:
                            mark_record_failed(db, record_id, ne.category, str(ne))
                        break
                else:
                    # Fail Closed
                    with SessionLocal() as db:
                        mark_record_failed(db, record_id, ne.category, str(ne))
                    break
                    
            except Exception as e:
                logger.error({"msg": "Unknown error", "job_id": job_id_val, "record_id": record_id, "attempt": attempt, "error": str(e)})
                with SessionLocal() as db:
                    mark_record_failed(db, record_id, ErrorCategory.UNKNOWN, str(e))
                break
                
            finally:
                # Update automated duration after each attempt
                automated_duration = (time.time() - automated_start) - human_wait_duration
                automated_start = time.time() # Reset for next attempt
                human_wait_duration = 0.0 # Reset for next attempt
                with SessionLocal() as db:
                    r = db.query(JobRecord).filter(JobRecord.id == record_id).first()
                    if r:
                        r.automated_duration_seconds = (r.automated_duration_seconds or 0) + max(0.0, automated_duration)
                        db.commit()
