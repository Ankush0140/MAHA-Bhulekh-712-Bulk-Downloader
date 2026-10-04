import pytest
from unittest.mock import AsyncMock, MagicMock
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from app.automation.navigation import navigate_to_bhulekh_home, NavigationError
from app.models.enums import ErrorCategory

@pytest.fixture
def mock_page():
    page = AsyncMock()
    return page

@pytest.mark.asyncio
async def test_navigate_to_bhulekh_home_success(mock_page):
    await navigate_to_bhulekh_home(mock_page)
    mock_page.goto.assert_called_once_with(
        "https://bhulekh.mahabhumi.gov.in/", 
        wait_until="domcontentloaded", 
        timeout=60000
    )
    mock_page.wait_for_selector.assert_called_once()

@pytest.mark.asyncio
async def test_navigate_to_bhulekh_home_timeout(mock_page):
    mock_page.goto.side_effect = PlaywrightTimeoutError("Timeout 60000ms exceeded.")
    
    with pytest.raises(NavigationError) as exc:
        await navigate_to_bhulekh_home(mock_page)
        
    assert exc.value.category == ErrorCategory.TIMEOUT

@pytest.mark.asyncio
async def test_navigate_to_bhulekh_home_other_error(mock_page):
    mock_page.goto.side_effect = Exception("Some unknown DNS error")
    
    with pytest.raises(NavigationError) as exc:
        await navigate_to_bhulekh_home(mock_page)
        
    assert exc.value.category == ErrorCategory.UNKNOWN
