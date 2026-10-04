import asyncio
import random
from typing import Set

from app.models.enums import ErrorCategory

# --- ERROR CLASSIFICATIONS ---

TRANSIENT_AUTOMATIC_ERRORS: Set[ErrorCategory] = {
    ErrorCategory.TIMEOUT,
    ErrorCategory.NETWORK_ERROR,
}

HUMAN_SESSION_ERRORS: Set[ErrorCategory] = {
    ErrorCategory.CAPTCHA_REQUIRED,
    ErrorCategory.SESSION_EXPIRED,
}

FAIL_CLOSED_ERRORS: Set[ErrorCategory] = {
    ErrorCategory.LOCATION_SELECTION_MISMATCH,
    ErrorCategory.SURVEY_SELECTION_MISMATCH,
    ErrorCategory.PORTAL_LAYOUT_CHANGED,
}

CAPTURE_ERRORS: Set[ErrorCategory] = {
    ErrorCategory.CAPTURE_ERROR,
    ErrorCategory.PDF_WRITE_ERROR,
}

# --- CONFIGURATION ---

MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 2.0
MAX_BACKOFF_SECONDS = 10.0
RATE_LIMIT_DELAY_SECONDS = 1.0

# --- POLICIES ---

def is_retryable_error(category: ErrorCategory) -> bool:
    """Determine if the error is eligible for automated transient retry."""
    return category in TRANSIENT_AUTOMATIC_ERRORS or category in CAPTURE_ERRORS

def is_human_session_error(category: ErrorCategory) -> bool:
    """Determine if the error requires a fresh human session/CAPTCHA."""
    return category in HUMAN_SESSION_ERRORS

def get_backoff_delay(attempt: int) -> float:
    """Calculate exponential backoff with jitter."""
    if attempt <= 1:
        return 0.0
    
    # 2, 4, 8...
    delay = BASE_BACKOFF_SECONDS * (2 ** (attempt - 2))
    delay = min(delay, MAX_BACKOFF_SECONDS)
    
    # Add +/- 20% jitter
    jitter = delay * 0.2
    return delay + random.uniform(-jitter, jitter)

async def apply_rate_limit(enabled: bool = True):
    """Polite delay between portal operations/records."""
    if enabled and RATE_LIMIT_DELAY_SECONDS > 0:
        await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)

async def apply_backoff(attempt: int, enabled: bool = True):
    """Sleep for the appropriate backoff duration based on attempt number."""
    if not enabled:
        return
        
    delay = get_backoff_delay(attempt)
    if delay > 0:
        await asyncio.sleep(delay)
