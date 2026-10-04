import asyncio
import re
from typing import Optional
from sqlalchemy.orm import Session
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.models.db import Job
from app.automation.selectors import (
    DISTRICT_SELECT, TALUKA_SELECT, VILLAGE_SELECT,
    SEARCH_TYPE_SELECT, SEARCH_MODE_NUMERIC,
    PART1_INPUT, SEARCH_BUTTON, SURVEY_RESULT_SELECT,
    RESULT_IMAGE
)
from app.models.enums import ErrorCategory

class NavigationError(Exception):
    def __init__(self, message: str, category: ErrorCategory):
        super().__init__(message)
        self.category = category

async def navigate_to_bhulekh_home(page: Page, timeout_ms: int = 60000):
    """
    Centralized helper to safely navigate to the Bhulekh homepage.
    Uses 'domcontentloaded' to avoid waiting for slow external resources.
    Waits for a critical DOM element to verify form readiness.
    Converts Playwright timeouts to transient ErrorCategory.TIMEOUT.
    """
    try:
        await page.goto("https://bhulekh.mahabhumi.gov.in/", wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=15000)
    except PlaywrightTimeoutError as e:
        raise NavigationError(f"Timeout loading Bhulekh homepage: {e}", ErrorCategory.TIMEOUT)
    except Exception as e:
        raise NavigationError(f"Failed to load Bhulekh homepage: {e}", ErrorCategory.UNKNOWN)

async def select_location(page: Page, job: Job):
    """Reselects district, taluka, village based on Job persistence."""
    try:
        # District
        await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=10000)
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            if job.district_value:
                await page.locator(DISTRICT_SELECT).select_option(value=job.district_value)
            else:
                await page.locator(DISTRICT_SELECT).select_option(label=job.district_text)
        await page.wait_for_load_state("domcontentloaded")
        
        # Taluka
        await page.wait_for_selector(TALUKA_SELECT, state="visible", timeout=10000)
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            if job.taluka_value:
                await page.locator(TALUKA_SELECT).select_option(value=job.taluka_value)
            else:
                await page.locator(TALUKA_SELECT).select_option(label=job.taluka_text)
        await page.wait_for_load_state("domcontentloaded")
        
        # Village
        await page.wait_for_selector(VILLAGE_SELECT, state="visible", timeout=10000)
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            if job.village_value:
                await page.locator(VILLAGE_SELECT).select_option(value=job.village_value)
            else:
                await page.locator(VILLAGE_SELECT).select_option(label=job.village_text)
        await page.wait_for_load_state("domcontentloaded")
        
        # Verify Verification (checking text)
        dist_text = await page.locator(f"{DISTRICT_SELECT} option:checked").inner_text()
        tal_text = await page.locator(f"{TALUKA_SELECT} option:checked").inner_text()
        vill_text = await page.locator(f"{VILLAGE_SELECT} option:checked").inner_text()
        
        if job.district_text not in dist_text or job.taluka_text not in tal_text or job.village_text not in vill_text:
            raise NavigationError("Location verification failed", ErrorCategory.LOCATION_SELECTION_MISMATCH)
            
    except PlaywrightTimeoutError as e:
        raise NavigationError(f"Timeout during location selection: {e}", ErrorCategory.TIMEOUT)
    except NavigationError:
        raise
    except Exception as e:
        raise NavigationError(f"Error during location selection: {e}", ErrorCategory.UNKNOWN)

async def wait_for_aspnet_postback(page: Page, trigger_selector: str):
    """
    Triggers an action (click) and deterministically waits for the ASP.NET
    Sys.WebForms.PageRequestManager async postback to fully complete using native events.
    """
    await page.evaluate(f"""(sel) => {{
        return new Promise((resolve, reject) => {{
            const btn = document.querySelector(sel);
            if (!btn) {{
                reject(new Error("Trigger element not found: " + sel));
                return;
            }}
            
            if (typeof Sys !== 'undefined' && Sys.WebForms && Sys.WebForms.PageRequestManager) {{
                const prm = Sys.WebForms.PageRequestManager.getInstance();
                const endHandler = function(sender, args) {{
                    prm.remove_endRequest(endHandler);
                    resolve("POSTBACK_COMPLETE");
                }};
                prm.add_endRequest(endHandler);
                btn.click();
                
                // Fallback for fast completion or no actual postback triggered
                setTimeout(() => {{
                    if (!prm.get_isInAsyncPostBack()) {{
                        prm.remove_endRequest(endHandler);
                        resolve("NO_POSTBACK_STARTED_OR_FINISHED_FAST");
                    }}
                }}, 500);
            }} else {{
                btn.click();
                resolve("NO_PRM_FOUND");
            }}
        }});
    }}""", trigger_selector)

import logging
logger = logging.getLogger(__name__)

async def prepare_record(page: Page, survey_identifier_original: str, job_id: int = 0, record_id: int = 0):
    """Search and select the exact Survey/Gat record."""
    try:
        # Ensure Numeric mode
        current_mode = await page.locator(SEARCH_TYPE_SELECT).evaluate("el => el.value")
        if current_mode != SEARCH_MODE_NUMERIC:
            async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=15000):
                await page.locator(SEARCH_TYPE_SELECT).select_option(SEARCH_MODE_NUMERIC)
            await page.wait_for_load_state("domcontentloaded")

        # Get Prefix
        match = re.match(r"^(\d+)", survey_identifier_original)
        prefix = match.group(1) if match else survey_identifier_original

        input_elem = page.locator(PART1_INPUT)
        await input_elem.fill("")
        await input_elem.fill(prefix)

        # Wait robustly for ASP.NET postback via PageRequestManager
        await wait_for_aspnet_postback(page, SEARCH_BUTTON)
        
        # Select exact survey
        dropdown = page.locator(SURVEY_RESULT_SELECT)
        
        # Extract options
        options = await page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (!el) return [];
            return Array.from(el.options).map(o => ({{
                text: o.text,
                value: o.value
            }}));
        }}""", SURVEY_RESULT_SELECT)
        
        from app.automation.text_utils import normalize_survey_identifier
        
        norm_target = normalize_survey_identifier(survey_identifier_original)
        target_val = None
        
        for o in options:
            if normalize_survey_identifier(o['text']) == norm_target:
                target_val = o['value']
                break
                
        logger.info({
            "msg": "Survey selection diagnostic",
            "job_id": job_id,
            "record_id": record_id,
            "expected_survey": survey_identifier_original,
            "search_prefix": prefix,
            "dropdown_option_count": len(options),
            "exact_match_found": target_val is not None,
            "selected_value": target_val
        })
                
        if target_val is None:
            raise NavigationError(
                f"Expected survey '{survey_identifier_original}' was not present after search prefix '{prefix}'.",
                ErrorCategory.SURVEY_SELECTION_MISMATCH
            )
            
        async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
            await dropdown.select_option(value=target_val)
            
        await page.wait_for_load_state("domcontentloaded")
        
        # Verify
        selected_text = await page.locator(f"{SURVEY_RESULT_SELECT} option:checked").inner_text()
        if normalize_survey_identifier(selected_text) != norm_target:
            raise NavigationError("Survey verification failed", ErrorCategory.SURVEY_SELECTION_MISMATCH)

    except PlaywrightTimeoutError as e:
        raise NavigationError(f"Timeout during survey selection: {e}", ErrorCategory.TIMEOUT)
    except NavigationError:
        raise
    except Exception as e:
        raise NavigationError(f"Error during survey selection: {e}", ErrorCategory.UNKNOWN)

class HumanWaitTimeout(Exception):
    pass

class PauseRequested(Exception):
    pass

class SessionResetDetected(Exception):
    pass

class InvisibleWindowError(Exception):
    pass

async def wait_for_human_result(page: Page, job_id: int, timeout_ms: int = 3600000, target_title: str = None) -> None:
    """
    Polls for human to solve CAPTCHA and submit.
    Checks for Job pause requests and structural session reset.
    timeout_ms defaults to 1 hour (3600000 ms).
    """
    import time
    from app.services.db_service import get_job
    from app.dependencies import SessionLocal
    
    start_time = time.time()
    max_duration = timeout_ms / 1000.0
    
    while True:
        if time.time() - start_time > max_duration:
            raise HumanWaitTimeout("Maximum human wait time exceeded.")
            
        # 1. Check Job Pause
        with SessionLocal() as db:
            job = get_job(db, job_id)
            if job and job.pause_requested:
                raise PauseRequested("Pause requested during human wait.")
                
        # 1.5 Check Window Visibility
        if target_title:
            from app.automation.window_check import has_visible_window_with_title
            
            if page.is_closed():
                raise InvisibleWindowError("Playwright page is closed.")
                
            if not has_visible_window_with_title(target_title):
                # Bounded retry for OS window title update race condition
                is_visible = False
                for _ in range(5):
                    await asyncio.sleep(0.5)
                    if has_visible_window_with_title(target_title):
                        is_visible = True
                        break
                        
                if not is_visible:
                    try:
                        actual_title = await page.title()
                        actual_url = page.url
                    except Exception:
                        actual_title = "ERROR_FETCHING_TITLE"
                        actual_url = "ERROR_FETCHING_URL"
                        
                    logger.error({
                        "msg": "Window invisibility diagnostic",
                        "job_id": job_id,
                        "expected_title": target_title,
                        "actual_title": actual_title,
                        "url": actual_url,
                        "reason": "has_visible_window_with_title returned False after retries",
                    })
                    raise InvisibleWindowError("Browser window is inherently invisible or closed")
            
        # 2. Check for Success (Result Image)
        try:
            # Quick check without waiting
            img_valid = await page.evaluate(f"""() => {{
                const img = document.querySelector('{RESULT_IMAGE}');
                if (!img || !img.src) return false;
                if (img.naturalWidth === 0 || img.naturalHeight === 0) return false;
                return true;
            }}""")
            if img_valid:
                return # Success!
        except Exception:
            pass # Ignore page evaluation errors during polling
            
        # 3. Check for Structural Session Reset (Layer 1)
        # If the input fields we just filled are suddenly gone, but the page is still loaded.
        is_reset = False
        try:
            is_reset = await page.evaluate(f"""() => {{
                const dist = document.querySelector('{DISTRICT_SELECT}');
                // If the element exists but has no selected value (or default 'Select' value)
                if (dist && (!dist.value || dist.value === '0' || dist.value === '')) {{
                    return true;
                }}
                return false;
            }}""")
        except Exception:
            pass
            
        if is_reset:
            raise SessionResetDetected("Structural session reset detected.")
            
        # Sleep for polling interval
        await asyncio.sleep(2.0)
