import os
from typing import Optional, Tuple
from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
import logging

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
DEFAULT_HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"

# Explicit host-scoped TLS exception because the official Bhulekh portal
# currently presents an expired certificate (SEC_E_CERT_EXPIRED / ERR_CERT_DATE_INVALID).
# This is NOT a global ignore_https_errors.
BHULEKH_ALLOW_EXPIRED_TLS = True

async def launch_browser_and_context(
    playwright: Playwright,
    channel: Optional[str] = DEFAULT_CHANNEL,
    headless: bool = DEFAULT_HEADLESS,
    is_bhulekh_context: bool = True
) -> Tuple[Browser, BrowserContext]:
    """
    Launch Playwright chromium with a specified channel (e.g. 'chrome', 'msedge', or None for bundled Chromium).
    Centralized browser manager to avoid hardcoding launch parameters across multiple files.
    """
    launch_kwargs = {"headless": headless}
    if channel and channel.strip():
        launch_kwargs["channel"] = channel.strip()

    try:
        browser = await playwright.chromium.launch(**launch_kwargs)
    except Exception as e:
        # Fallback explanation if channel is not found
        if channel:
            raise RuntimeError(
                f"Failed to launch browser with channel='{channel}'. "
                f"Ensure Google Chrome or Microsoft Edge is installed on Windows. Original error: {e}"
            ) from e
        raise e

    context_kwargs = {
        "viewport": {"width": 1280, "height": 800},
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    if is_bhulekh_context and BHULEKH_ALLOW_EXPIRED_TLS:
        logger.warning(
            "TLS verification is relaxed (ignore_https_errors=True) in this context because the configured "
            "official Bhulekh portal currently presents an expired certificate."
        )
        context_kwargs["ignore_https_errors"] = True

    context = await browser.new_context(**context_kwargs)

    if is_bhulekh_context and BHULEKH_ALLOW_EXPIRED_TLS:
        async def restrict_tls_bypass(route):
            url = route.request.url
            if route.request.is_navigation_request() and not url.startswith("https://bhulekh.mahabhumi.gov.in"):
                logger.error(f"Blocked navigation to {url} because it is outside the allowed TLS exception origin.")
                await route.abort("accessdenied")
            else:
                await route.continue_()
        await context.route("**/*", restrict_tls_bypass)

    return browser, context


# The job workflow ends at the official Bhulekh mobile/CAPTCHA form, which a human
# must complete in this exact browser window. It must therefore never be headless,
# regardless of the HEADLESS environment setting used for background metadata reads.
HUMAN_WORKFLOW_CHANNEL = "chrome"
HUMAN_WORKFLOW_HEADLESS = False


async def launch_human_workflow_browser(playwright: Playwright) -> Tuple[Browser, BrowserContext]:
    """Launch the visible installed-Chrome browser used for human CAPTCHA/mobile entry."""
    return await launch_browser_and_context(
        playwright,
        channel=HUMAN_WORKFLOW_CHANNEL,
        headless=HUMAN_WORKFLOW_HEADLESS,
    )
