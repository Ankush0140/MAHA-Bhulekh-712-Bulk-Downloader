import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Callable
from playwright.async_api import Page

from app.automation.selectors import (
    SEARCH_TYPE_SELECT,
    SEARCH_MODE_NUMERIC,
    PART1_INPUT,
    SEARCH_BUTTON,
    SURVEY_RESULT_SELECT
)
from app.automation.errors import PortalLayoutChanged, DiscoveryError


@dataclass
class SurveyRecord:
    display_text: str
    option_value: str
    source_prefix: str
    discovery_order: int


@dataclass
class DiscoveryResult:
    records: List[SurveyRecord] = field(default_factory=list)
    total_unique: int = 0
    prefix_counts: Dict[str, int] = field(default_factory=dict)
    duplicates_removed: int = 0
    failed_prefixes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def is_placeholder_option(text: str, value: str) -> bool:
    """Identify placeholder select options such as '--निवडा--'."""
    txt = text.strip()
    val = value.strip()
    return "निवडा" in txt or val in ["0", "-1", ""]


def compute_options_signature(options: List[Dict[str, str]]) -> str:
    """Compute MD5 signature of option list for change detection."""
    raw = "|".join([f"{opt.get('value', '')}:{opt.get('text', '')}" for opt in options])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def process_and_deduplicate_options(
    raw_options: List[Dict[str, str]],
    source_prefix: str,
    seen_identities: Set[tuple],
    records_list: List[SurveyRecord]
) -> tuple[int, int]:
    """
    Filter placeholders and deduplicate records by exact (option_value, display_text) identity.
    Preserves original text, value, slashes, Latin characters, and Devanagari suffixes.
    Returns (valid_count_for_prefix, duplicates_for_prefix).
    """
    valid_count = 0
    dup_count = 0

    from app.automation.text_utils import normalize_survey_identifier

    for opt in raw_options:
        text = normalize_survey_identifier(opt.get("text", ""))
        val = opt.get("value", "").strip()

        if is_placeholder_option(text, val):
            continue

        valid_count += 1
        identity = (val, text)

        if identity in seen_identities:
            dup_count += 1
        else:
            seen_identities.add(identity)
            rec = SurveyRecord(
                display_text=text,
                option_value=val,
                source_prefix=source_prefix,
                discovery_order=len(records_list) + 1
            )
            records_list.append(rec)

    return valid_count, dup_count


async def extract_select_options(page: Page, selector: str) -> List[Dict[str, str]]:
    """Extract option text and value pairs from a select element on the page."""
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
        raise PortalLayoutChanged(f"Failed to read dropdown element at {selector}: {e}") from e


async def discover_numeric_surveys(
    page: Page,
    prefixes: Optional[List[str]] = None,
    request_delay: float = 0.5,
    validate_completeness: bool = False,
    on_progress: Optional[Callable[[str, int, int], None]] = None
) -> DiscoveryResult:
    """
    Production Numeric Survey/Gat Discovery Service.
    Sequentially searches numeric prefixes (default '1' through '9'), handles postback synchronization,
    deduplicates exact records, and returns structured DiscoveryResult metadata.
    """
    if prefixes is None:
        prefixes = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

    start_time = time.time()
    result = DiscoveryResult()

    # 1. Verify required DOM controls exist
    for sel in [SEARCH_TYPE_SELECT, PART1_INPUT, SEARCH_BUTTON, SURVEY_RESULT_SELECT]:
        if not await page.locator(sel).is_visible():
            raise PortalLayoutChanged(f"Required discovery selector missing or hidden: {sel}")

    # 2. Ensure Numeric Search Mode ('2') is active
    current_mode = await page.locator(SEARCH_TYPE_SELECT).evaluate("el => el.value")
    if current_mode != SEARCH_MODE_NUMERIC:
        async with page.expect_response(
            lambda r: r.request.method == "POST" and "mahabhumi.gov.in" in r.url,
            timeout=15000
        ):
            await page.locator(SEARCH_TYPE_SELECT).select_option(SEARCH_MODE_NUMERIC)
        await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(1.0)

    seen_identities: Set[tuple] = set()

    # 3. Iterate through specified numeric prefixes
    for prefix in prefixes:
        try:
            input_elem = page.locator(PART1_INPUT)
            await input_elem.fill("")
            await input_elem.fill(prefix)

            # Verify input value
            verified_val = await input_elem.input_value()
            if verified_val != prefix:
                raise DiscoveryError(f"Input verification failed for prefix '{prefix}'. Got '{verified_val}'")

            pre_options = await extract_select_options(page, SURVEY_RESULT_SELECT)
            pre_sig = compute_options_signature(pre_options)

            # Click Search button and wait robustly for ASP.NET postback via PageRequestManager
            from app.automation.navigation import wait_for_aspnet_postback
            await wait_for_aspnet_postback(page, SEARCH_BUTTON)

            post_options = await extract_select_options(page, SURVEY_RESULT_SELECT)
            post_sig = compute_options_signature(post_options)

            # Check for stale dropdown state
            if pre_sig == post_sig and len(pre_options) > 0:
                result.warnings.append(f"Stale dropdown detected for prefix '{prefix}' (search postback may have been skipped).")

            valid_count, dup_count = process_and_deduplicate_options(
                post_options, prefix, seen_identities, result.records
            )

            result.prefix_counts[prefix] = valid_count
            result.duplicates_removed += dup_count

            if on_progress:
                on_progress(prefix, valid_count, len(result.records))

        except Exception as err:
            result.failed_prefixes.append(prefix)
            result.warnings.append(f"Failed prefix '{prefix}': {err}")

    # 4. Optional lightweight completeness validation (e.g. comparing prefix '10' vs '1')
    if validate_completeness and "1" in prefixes:
        try:
            child_prefix = "10"
            input_elem = page.locator(PART1_INPUT)
            await input_elem.fill("")
            await input_elem.fill(child_prefix)

            await wait_for_aspnet_postback(page, SEARCH_BUTTON)
            child_options = await extract_select_options(page, SURVEY_RESULT_SELECT)
            child_clean = [opt["value"] for opt in child_options if not is_placeholder_option(opt["text"], opt["value"])]

            parent_records = {r.option_value for r in result.records if r.source_prefix == "1"}
            missing_in_parent = set(child_clean) - parent_records

            if missing_in_parent:
                result.warnings.append(
                    f"POSSIBLE_TRUNCATION: {len(missing_in_parent)} items from child prefix '{child_prefix}' missing in parent prefix '1'."
                )
        except Exception as val_err:
            result.warnings.append(f"Completeness validation check error: {val_err}")

    result.total_unique = len(result.records)
    result.elapsed_seconds = round(time.time() - start_time, 2)
    return result
