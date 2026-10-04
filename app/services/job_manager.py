import asyncio
import logging
import threading
from typing import Dict
from playwright.async_api import async_playwright
from app.models.db import Job
from app.models.enums import JobStatus
from app.services.db_service import get_job, update_job_status, reconcile_interrupted_jobs, upsert_discovered_records, release_human_wait_state
from app.automation.worker import Worker
from app.automation.browser import launch_human_workflow_browser
from app.automation.discovery import discover_numeric_surveys
from app.dependencies import SessionLocal, DB_PATH
from app.config import BASE_DIR
from app.models.location import LocationSelection
from app.automation.navigation import select_location

logger = logging.getLogger(__name__)

class JobManager:
    def __init__(self):
        self.active_tasks: Dict[int, asyncio.Task] = {}
        self.base_output_dir = BASE_DIR / "output"
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.global_portal_lock = asyncio.Lock()

    def init_app(self):
        with SessionLocal() as db:
            reconcile_interrupted_jobs(db, self.base_output_dir)

    def shutdown(self):
        for task in self.active_tasks.values():
            task.cancel()

    async def _run_job_workflow(self, job_id: int):
        playwright = None
        browser = None
        try:
            with SessionLocal() as db:
                job = get_job(db, job_id)
                if not job:
                    return

                if job.status == JobStatus.CREATED:
                    update_job_status(db, job_id, JobStatus.DISCOVERING)
                    job = get_job(db, job_id)

                loc = LocationSelection(
                    division_text=job.division_text, division_value=job.division_value,
                    district_text=job.district_text, district_value=job.district_value,
                    taluka_text=job.taluka_text, taluka_value=job.taluka_value,
                    village_text=job.village_text, village_value=job.village_value
                )

            playwright = await async_playwright().start()
            browser, context = await launch_human_workflow_browser(playwright)
            page = await context.new_page()

            with SessionLocal() as db:
                job = get_job(db, job_id)
                if job.status == JobStatus.DISCOVERING:
                    # Discover records
                    try:
                        await page.goto("https://bhulekh.mahabhumi.gov.in/", timeout=60000)
                        await page.wait_for_load_state("domcontentloaded")
                        await select_location(page, job)
                        
                        # Just discover numeric 1-9 for now
                        discovery_res = await discover_numeric_surveys(page)
                        
                        survey_identifiers = [r.display_text for r in discovery_res.records]
                        upsert_discovered_records(db, job_id, survey_identifiers)
                        
                        if discovery_res.total_unique == 0:
                            update_job_status(db, job_id, JobStatus.COMPLETED)
                            return
                        else:
                            update_job_status(db, job_id, JobStatus.RUNNING)
                    except Exception as e:
                        logger.error(f"Discovery failed for job {job_id}: {e}")
                        with SessionLocal() as db_err:
                            job_err = get_job(db_err, job_id)
                            job_err.status = JobStatus.FAILED
                            job_err.last_error_message = str(e)
                            db_err.commit()
                        return
                        
            # Worker phase
            worker = Worker(job_id, self.base_output_dir)
            await worker.run(page)

        except asyncio.CancelledError:
            logger.info(f"Task for job {job_id} cancelled.")
        except Exception as e:
            logger.error(f"Job {job_id} encountered unhandled error: {e}", exc_info=True)
            with SessionLocal() as db_err:
                update_job_status(db_err, job_id, JobStatus.FAILED)
        finally:
            # The browser holding the prepared CAPTCHA page is about to close; a
            # WAITING_FOR_CAPTCHA state must not be left persisted without it.
            try:
                with SessionLocal() as db_rel:
                    release_human_wait_state(db_rel, job_id)
            except Exception as rel_err:
                logger.error(f"Failed to release human-wait state for job {job_id}: {rel_err}")
            if browser:
                await browser.close()
            if playwright:
                await playwright.stop()
            self.active_tasks.pop(job_id, None)

    def start_job(self, job_id: int):
        with self._lock:
            # Enforce global concurrency = 1: do not allow starting if any job is already running
            if len(self.active_tasks) > 0:
                if job_id not in self.active_tasks:
                    return False # Another job is already running
            if job_id in self.active_tasks:
                return False # Already running
            
            # Since this might be called from a sync route, we need to schedule it on the main loop
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._run_job_workflow(job_id))
            except RuntimeError:
                # If no running loop in this thread, we shouldn't be here in a FastAPI app unless it's weirdly configured.
                # Just in case, we can't easily create a task. Assuming FastAPI runs this on the main loop thread if we make the route async.
                task = asyncio.create_task(self._run_job_workflow(job_id))
                
            self.active_tasks[job_id] = task
            return True

job_manager = JobManager()
