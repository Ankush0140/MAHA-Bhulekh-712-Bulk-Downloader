from typing import List, Optional
import logging
from app.schemas import LocationItem
from app.data.maharashtra_divisions import get_divisions_metadata, get_division_for_district

logger = logging.getLogger(__name__)

# Mock / Interface for portal-backed location lookup

async def get_divisions() -> List[LocationItem]:
    """
    Returns application-side verified divisions.
    These are not portal values.
    """
    metadata = get_divisions_metadata()
    return [LocationItem(text=d["text"], value=d["value"]) for d in metadata]

async def _fetch_portal_districts() -> List[LocationItem]:
    """
    Return the Bhulekh District options.
    These are the exact 35 label/value pairs captured from the live portal
    District dropdown in Phase 10.6 (scripts/inspect_live_district_options.py).
    """
    return [
        LocationItem(text="अकोला", value="5"),
        LocationItem(text="अमरावती", value="7"),
        LocationItem(text="बुलडाणा", value="4"),
        LocationItem(text="यवतमाळ", value="14"),
        LocationItem(text="वाशिम", value="6"),
        LocationItem(text="धाराशिव", value="29"),
        LocationItem(text="छत्रपती संभाजीनगर", value="19"),
        LocationItem(text="जालना", value="18"),
        LocationItem(text="नांदेड", value="15"),
        LocationItem(text="परभणी", value="17"),
        LocationItem(text="बीड", value="27"),
        LocationItem(text="लातूर", value="28"),
        LocationItem(text="हिंगोली", value="16"),
        LocationItem(text="ठाणे", value="21"),
        LocationItem(text="पालघर", value="36"),
        LocationItem(text="मंबई उपनगर", value="22"),
        LocationItem(text="रत्नागिरी", value="32"),
        LocationItem(text="रायगड", value="24"),
        LocationItem(text="सिंधुदुर्ग", value="33"),
        LocationItem(text="गडचिरोली", value="12"),
        LocationItem(text="गोंदिया", value="11"),
        LocationItem(text="चंद्रपूर", value="13"),
        LocationItem(text="नागपूर", value="9"),
        LocationItem(text="भंडारा", value="10"),
        LocationItem(text="वर्धा", value="8"),
        LocationItem(text="अहिल्यानगर", value="26"),
        LocationItem(text="जळगाव", value="3"),
        LocationItem(text="धुळे", value="2"),
        LocationItem(text="नंदुरबार", value="1"),
        LocationItem(text="नाशिक", value="20"),
        LocationItem(text="कोल्हापूर", value="34"),
        LocationItem(text="पुणे", value="25"),
        LocationItem(text="सांगली", value="35"),
        LocationItem(text="सातारा", value="31"),
        LocationItem(text="सोलापूर", value="30"),
    ]

async def get_districts(division_value: Optional[str] = None) -> List[LocationItem]:
    """
    Fetch portal districts, and optionally filter by application-side division.
    """
    portal_districts = await _fetch_portal_districts()
    
    if not division_value:
        return portal_districts
        
    filtered = []
    for dist in portal_districts:
        div = get_division_for_district(dist.text)
        if div == division_value:
            filtered.append(dist)
        elif not div:
            logger.warning(f"Configuration mismatch: Portal district '{dist.text}' (value {dist.value}) could not be mapped to any division.")
            # We do NOT silently assign to a division, it's just excluded.
            
    return filtered

from app.automation.selectors import DISTRICT_SELECT, TALUKA_SELECT, VILLAGE_SELECT

async def get_talukas(district_value: str) -> List[LocationItem]:
    """Read live Taluka options from Bhulekh for the given portal District value."""
    from app.services.job_manager import job_manager
    from playwright.async_api import async_playwright
    from app.automation.browser import launch_browser_and_context
    from app.config import HEADLESS
    
    async with job_manager.global_portal_lock:
        async with async_playwright() as p:
            browser, context = await launch_browser_and_context(p, headless=HEADLESS)
            try:
                page = await context.new_page()
                from app.automation.navigation import navigate_to_bhulekh_home
                await navigate_to_bhulekh_home(page, timeout_ms=60000)
                await page.wait_for_load_state("domcontentloaded")
                
                await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=10000)
                async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
                    await page.locator(DISTRICT_SELECT).select_option(value=district_value)
                
                await page.wait_for_load_state("domcontentloaded")
                
                try:
                    await page.wait_for_function(f"""() => {{
                        const el = document.querySelector('{TALUKA_SELECT}');
                        return el && el.options.length > 1;
                    }}""", timeout=5000)
                except Exception:
                    pass
                    
                # Verify selected district
                dist_val = await page.locator(DISTRICT_SELECT).input_value()
                if dist_val != district_value:
                    raise Exception(f"District selection failed. Expected {district_value}, got {dist_val}.")
                
                options = await page.evaluate(f"""(sel) => {{
                    const el = document.querySelector(sel);
                    if (!el) return [];
                    return Array.from(el.options).map(o => ({{
                        text: o.text.trim(),
                        value: o.value
                    }}));
                }}""", TALUKA_SELECT)
                
                results = []
                for o in options:
                    if "निवडा" not in o["text"] and str(o["value"]) not in ["", "0", "-1"]:
                        results.append(LocationItem(text=o["text"], value=str(o["value"])))
                
                if not results:
                    raise Exception("No talukas found or portal unresponsive.")
                return results
            except Exception as e:
                logger.error(f"Failed to fetch talukas: {e}")
                raise Exception(f"Unable to load Talukas from Bhulekh. Please retry. ({str(e)})")
            finally:
                await browser.close()

async def get_villages(district_value: str, taluka_value: str) -> List[LocationItem]:
    """Read live Village options from Bhulekh for the given portal District/Taluka values."""
    from app.services.job_manager import job_manager
    from playwright.async_api import async_playwright
    from app.automation.browser import launch_browser_and_context
    from app.config import HEADLESS
    
    async with job_manager.global_portal_lock:
        async with async_playwright() as p:
            browser, context = await launch_browser_and_context(p, headless=HEADLESS)
            try:
                page = await context.new_page()
                from app.automation.navigation import navigate_to_bhulekh_home
                await navigate_to_bhulekh_home(page, timeout_ms=60000)
                await page.wait_for_load_state("domcontentloaded")
                
                await page.wait_for_selector(DISTRICT_SELECT, state="visible", timeout=10000)
                async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
                    await page.locator(DISTRICT_SELECT).select_option(value=district_value)
                
                await page.wait_for_load_state("domcontentloaded")
                
                await page.wait_for_selector(TALUKA_SELECT, state="visible", timeout=10000)
                async with page.expect_response(lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url, timeout=30000):
                    await page.locator(TALUKA_SELECT).select_option(value=taluka_value)
                    
                await page.wait_for_load_state("domcontentloaded")
                
                try:
                    await page.wait_for_function(f"""() => {{
                        const el = document.querySelector('{VILLAGE_SELECT}');
                        return el && el.options.length > 1;
                    }}""", timeout=5000)
                except Exception:
                    pass
                    
                # Verify selections
                dist_val = await page.locator(DISTRICT_SELECT).input_value()
                tal_val = await page.locator(TALUKA_SELECT).input_value()
                if dist_val != district_value or tal_val != taluka_value:
                    raise Exception(f"Location selection mismatch. Expected {district_value}/{taluka_value}, got {dist_val}/{tal_val}.")
                
                options = await page.evaluate(f"""(sel) => {{
                    const el = document.querySelector(sel);
                    if (!el) return [];
                    return Array.from(el.options).map(o => ({{
                        text: o.text.trim(),
                        value: o.value
                    }}));
                }}""", VILLAGE_SELECT)
                
                results = []
                for o in options:
                    if "निवडा" not in o["text"] and str(o["value"]) not in ["", "0", "-1"]:
                        results.append(LocationItem(text=o["text"], value=str(o["value"])))
                
                if not results:
                    raise Exception("No villages found or portal unresponsive.")
                return results
            except Exception as e:
                logger.error(f"Failed to fetch villages: {e}")
                raise Exception(f"Unable to load Villages from Bhulekh. Please retry. ({str(e)})")
            finally:
                await browser.close()
