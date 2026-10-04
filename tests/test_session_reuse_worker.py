import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.automation.worker import Worker
from app.models.db import Job, JobRecord
from app.models.enums import JobStatus, RecordStatus
from pathlib import Path

@pytest.fixture
def mock_db_session():
    with patch('app.automation.worker.SessionLocal') as mock_session_local:
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session
        yield mock_session

@pytest.fixture
def mock_page():
    return AsyncMock()

@pytest.mark.asyncio
async def test_worker_first_record_requires_human_wait_and_marks_reusable(mock_page, mock_db_session):
    # Setup mock job and record
    job = Job(id=1, status=JobStatus.RUNNING, district_text="D", taluka_text="T", village_text="V", total_records=1)
    record = JobRecord(id=1, job_id=1, survey_identifier_original="1", status=RecordStatus.PENDING, attempt_count=0)
    
    # Mocking db queries
    def query_side_effect(model):
        q = MagicMock()
        if model == Job:
            q.filter.return_value.first.return_value = job
        elif model == JobRecord:
            q.filter.return_value.order_by.return_value.first.return_value = record
            q.filter.return_value.first.return_value = record
            q.filter.return_value.count.return_value = 0 # for job counters
        return q
    mock_db_session.query.side_effect = query_side_effect

    worker = Worker(job_id=1, base_output_dir=Path("C:/tmp"))
    
    with patch('app.automation.worker.get_job', return_value=job), \
         patch('app.automation.worker.get_next_pending_record', return_value=record), \
         patch('app.automation.navigation.navigate_to_bhulekh_home', new_callable=AsyncMock) as mock_nav_home, \
         patch('app.automation.worker.select_location', new_callable=AsyncMock) as mock_sel_loc, \
         patch('app.automation.worker.prepare_record', new_callable=AsyncMock) as mock_prep_rec, \
         patch('app.automation.worker.wait_for_human_result', new_callable=AsyncMock) as mock_wait_human, \
         patch('app.automation.worker.extract_record_image', new_callable=AsyncMock) as mock_extract, \
         patch('app.automation.worker.save_record_pdf') as mock_save:
         
        # Simulate that CAPTCHA is required
        mock_locator = MagicMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        mock_page.locator = MagicMock(return_value=mock_locator) # CAPTCHA visible
        mock_page.evaluate.return_value = False # RESULT_IMAGE not visible
        
        mock_save.return_value.created = True
        mock_save.return_value.size_bytes = 100
        
        await worker.process_record(mock_page)
        
        mock_nav_home.assert_called_once()
        mock_wait_human.assert_called_once()
        assert worker.human_session_verified is True

@pytest.mark.asyncio
async def test_worker_successful_record_uses_back_flow(mock_page, mock_db_session):
    job = Job(id=1, status=JobStatus.RUNNING, district_text="D", taluka_text="T", village_text="V", total_records=1)
    record = JobRecord(id=2, job_id=1, survey_identifier_original="2", status=RecordStatus.PENDING, attempt_count=0)
    
    def query_side_effect(model):
        q = MagicMock()
        if model == Job:
            q.filter.return_value.first.return_value = job
        elif model == JobRecord:
            q.filter.return_value.order_by.return_value.first.return_value = record
            q.filter.return_value.first.return_value = record
            q.filter.return_value.count.return_value = 0 # for job counters
        return q
    mock_db_session.query.side_effect = query_side_effect

    worker = Worker(job_id=1, base_output_dir=Path("C:/tmp"))
    worker.human_session_verified = True # Reusing session
    
    with patch('app.automation.worker.get_job', return_value=job), \
         patch('app.automation.worker.get_next_pending_record', return_value=record), \
         patch('app.automation.navigation.return_to_search_form', new_callable=AsyncMock) as mock_return, \
         patch('app.automation.worker.select_location', new_callable=AsyncMock) as mock_sel_loc, \
         patch('app.automation.worker.prepare_record', new_callable=AsyncMock) as mock_prep_rec, \
         patch('app.automation.worker.wait_for_human_result', new_callable=AsyncMock) as mock_wait_human, \
         patch('app.automation.worker.extract_record_image', new_callable=AsyncMock) as mock_extract, \
         patch('app.automation.worker.save_record_pdf') as mock_save:
         
        # Simulate result image not visible after back
        async def evaluate_side_effect(script):
            if 'RESULT_IMAGE' in script and '!!document' in script:
                return False
            if 'naturalWidth' in script:
                return True # After prepare_record, assume result image pops up automatically
            return False
            
        mock_page.evaluate.side_effect = evaluate_side_effect
        mock_locator = MagicMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_page.locator = MagicMock(return_value=mock_locator) # Captcha not visible
        
        mock_save.return_value.created = True
        mock_save.return_value.size_bytes = 100
        
        await worker.process_record(mock_page)
        
        mock_return.assert_called_once()
        mock_sel_loc.assert_called_once()
        mock_wait_human.assert_not_called() # Skipping wait since image popped up
        assert worker.human_session_verified is True

@pytest.mark.asyncio
async def test_worker_session_expiry_returns_to_waiting_for_captcha(mock_page, mock_db_session):
    job = Job(id=1, status=JobStatus.RUNNING, district_text="D", taluka_text="T", village_text="V", total_records=1)
    record = JobRecord(id=3, job_id=1, survey_identifier_original="3", status=RecordStatus.PENDING, attempt_count=0)

    def query_side_effect(model):
        q = MagicMock()
        if model == Job:
            q.filter.return_value.first.return_value = job
        elif model == JobRecord:
            q.filter.return_value.order_by.return_value.first.return_value = record
            q.filter.return_value.first.return_value = record
            q.filter.return_value.count.return_value = 0 # for job counters
        return q
    mock_db_session.query.side_effect = query_side_effect

    worker = Worker(job_id=1, base_output_dir=Path("C:/tmp"))
    worker.human_session_verified = True
    
    with patch('app.automation.worker.get_job', return_value=job), \
         patch('app.automation.worker.get_next_pending_record', return_value=record), \
         patch('app.automation.navigation.return_to_search_form', new_callable=AsyncMock) as mock_return, \
         patch('app.automation.worker.select_location', new_callable=AsyncMock) as mock_sel_loc, \
         patch('app.automation.worker.prepare_record', new_callable=AsyncMock) as mock_prep_rec, \
         patch('app.automation.worker.wait_for_human_result', new_callable=AsyncMock) as mock_wait_human, \
         patch('app.automation.worker.extract_record_image', new_callable=AsyncMock) as mock_extract, \
         patch('app.automation.worker.save_record_pdf') as mock_save:
         
        # Simulate back successful, but prepare_record requires captcha
        async def evaluate_side_effect(script):
            return False # Image not visible
            
        mock_page.evaluate.side_effect = evaluate_side_effect
        mock_locator = MagicMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        mock_page.locator = MagicMock(return_value=mock_locator) # Captcha IS visible
        
        mock_save.return_value.created = True
        mock_save.return_value.size_bytes = 100
        
        await worker.process_record(mock_page)
        
        mock_wait_human.assert_called_once() # We had to wait for human again
        assert worker.human_session_verified is True # Resets to True after human wait succeeds
