import pytest
import ctypes
from unittest.mock import patch, MagicMock, AsyncMock

from app.automation.window_check import has_visible_window_with_title
from app.automation.navigation import wait_for_human_result, InvisibleWindowError

@pytest.fixture
def mock_winsta():
    with patch("app.automation.window_check._is_interactive_winsta", return_value=True) as m:
        yield m

def test_exact_native_title_match(mock_winsta):
    with patch("app.automation.window_check.get_visible_window_titles", return_value=["BHULEKH_JOB_1_RECORD_1_WAITING"]):
        assert has_visible_window_with_title("BHULEKH_JOB_1_RECORD_1_WAITING") is True

def test_chrome_suffix_title_match(mock_winsta):
    with patch("app.automation.window_check.get_visible_window_titles", return_value=["BHULEKH_JOB_1_RECORD_1_WAITING - Google Chrome"]):
        assert has_visible_window_with_title("BHULEKH_JOB_1_RECORD_1_WAITING") is True

def test_expected_unique_marker_prevents_matching_unrelated(mock_winsta):
    with patch("app.automation.window_check.get_visible_window_titles", return_value=["Some other job BHULEKH_JOB_99_RECORD_99_WAITING - Google Chrome"]):
        assert has_visible_window_with_title("BHULEKH_JOB_1_RECORD_1_WAITING") is False

def test_genuine_invisible_missing_window(mock_winsta):
    with patch("app.automation.window_check.get_visible_window_titles", return_value=["Other App Window", "Explorer"]):
        assert has_visible_window_with_title("WAITING") is False

@pytest.mark.asyncio
async def test_transient_enumwindows_false_negative_does_not_abort(mock_winsta):
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=False)
    
    with patch("app.automation.window_check.has_visible_window_with_title") as mock_has_visible:
        # Fails first 2 times, succeeds on 3rd
        mock_has_visible.side_effect = [False, False, True]
        
        # We also have to mock evaluate for the image check to return True so it exits
        mock_page.evaluate.return_value = True
        
        await wait_for_human_result(mock_page, 1, target_title="WAITING")
        assert mock_has_visible.call_count == 3

@pytest.mark.asyncio
async def test_closed_playwright_page_unavailable(mock_winsta):
    mock_page = AsyncMock()
    mock_page.is_closed = MagicMock(return_value=True)
    
    with pytest.raises(InvisibleWindowError, match="closed"):
        await wait_for_human_result(mock_page, 1, target_title="WAITING")
