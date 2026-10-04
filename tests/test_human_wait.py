import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.automation.worker import Worker
from app.services.db_service import update_job_status, get_job, mark_record_running
from app.models.db import JobRecord
from app.automation.navigation import NavigationError, wait_for_human_result, HumanWaitTimeout, PauseRequested, SessionResetDetected

@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    from app.dependencies import SessionLocal
    
    # Reconfigure the global SessionLocal to use the test engine
    SessionLocal.configure(bind=engine)
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.locator.return_value.evaluate = AsyncMock(return_value="2")
    page.locator.return_value.inner_text = AsyncMock(return_value="पुणे")
    return page

@pytest.fixture
def sample_job(db_session):
    from app.models.location import LocationSelection
    from app.services.db_service import create_job, upsert_discovered_records
    loc = LocationSelection(
        district_text="पुणे", district_value="1",
        taluka_text="मावळ", taluka_value="2",
        village_text="शिवाळी", village_value="3",
        division_text=None, division_value=None
    )
    job = create_job(db_session, loc)
    upsert_discovered_records(db_session, job.id, ["10/1"])
    return job

@pytest.mark.asyncio
async def test_human_wait_exceeds_five_minutes_without_automation_timeout(mock_page, db_session, sample_job):
    # Simulate a human wait timeout by configuring max wait to be 0 for test speed
    mock_page.evaluate.return_value = False
    with pytest.raises(HumanWaitTimeout):
        # Even with timeout=0, sleep might be needed to let time tick, but time.sleep inside loop?
        # A small negative max_duration guarantees immediate failure
        await wait_for_human_result(mock_page, sample_job.id, timeout_ms=-1000)

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_human_wait_timeout_behavior(
    mock_wait, mock_backoff, mock_select, mock_prepare, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Tests 1-4: Wait timeout does not increment attempt count or call backoff
    mock_wait.side_effect = HumanWaitTimeout()
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    await worker.run(mock_page)
    db_session.expire_all()
    
    db_session.refresh(sample_job)
    assert sample_job.status == JobStatus.PAUSED
    
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert records[0].status == RecordStatus.WAITING_FOR_CAPTCHA
    assert records[0].attempt_count == 1 # Only the first initial attempt was counted
    assert mock_backoff.call_count == 0
    assert mock_prepare.call_count == 1 # No automatic reload

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_pause_requested_during_human_wait(
    mock_wait, mock_backoff, mock_select, mock_prepare, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Tests 5-7: Pause during human wait exits safely without submit
    async def fake_wait(*args, **kwargs):
        # Simulate an external actor requesting pause during human wait
        job = get_job(db_session, sample_job.id)
        job.pause_requested = True
        db_session.commit()
        raise PauseRequested()
        
    mock_wait.side_effect = fake_wait
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    
    await worker.run(mock_page)
    db_session.expire_all()
    
    # Check it exited safely and left it WAITING_FOR_CAPTCHA
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert records[0].status == RecordStatus.WAITING_FOR_CAPTCHA
    assert mock_save.call_count == 0 # never submits/saves
    
@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_session_reset_recovery(
    mock_wait, mock_backoff, mock_select, mock_prepare, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Tests 16-20: Session reset invokes safe recovery
    # We'll simulate a SessionResetDetected, which should exit the inner loop,
    # and because the record is still WAITING_FOR_CAPTCHA, the outer loop fetches it again
    # and restarts preparation! Then we succeed.
    mock_wait.side_effect = [SessionResetDetected(), None]
    mock_save.return_value = MagicMock(created=True, size_bytes=100)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    await worker.run(mock_page)
    db_session.expire_all()
    
    # Prepared twice (initial + recovery)
    assert mock_prepare.call_count == 2
    # Select location twice
    assert mock_select.call_count == 2
    
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert records[0].status == RecordStatus.COMPLETED
    assert records[0].attempt_count == 2
    
@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_automation_preparation_timeout_increments_attempts(
    mock_wait, mock_backoff, mock_select, mock_prepare, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Tests 9-12: Three automated attempts persist correct count
    mock_prepare.side_effect = NavigationError("Network/Timeout", ErrorCategory.TIMEOUT)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    await worker.run(mock_page)
    db_session.expire_all()
    
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert records[0].status == RecordStatus.FAILED
    assert records[0].attempt_count == 3
    
@pytest.mark.asyncio
async def test_structural_session_reset_detection(mock_page, db_session, sample_job):
    # Test 15, 21: Fake page state detecting reset
    # We need page.evaluate to return False for img_valid, and True for is_reset
    mock_page.evaluate.side_effect = [False, True]
    with pytest.raises(SessionResetDetected):
        await wait_for_human_result(mock_page, sample_job.id, timeout_ms=3000)
    
    # If district select exists and has valid value, it's NOT a reset
    # We mock evaluate to return False (no reset, and no valid image)
    # Then it should just loop until timeout
    mock_page.evaluate.side_effect = [False, False, False, False]
    with pytest.raises(HumanWaitTimeout):
        # Very short timeout so it loops once and fails
        await wait_for_human_result(mock_page, sample_job.id, timeout_ms=500)
        
@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
async def test_human_timing_separated(
    mock_backoff, mock_select, mock_prepare, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Tests 22-23
    # We will mock wait_for_human_result directly to simulate a 0.5s human wait
    async def fake_wait(*args, **kwargs):
        await asyncio.sleep(0.5)
        
    with patch("app.automation.worker.wait_for_human_result", side_effect=fake_wait):
        mock_save.return_value = MagicMock(created=True, size_bytes=100)
        worker = Worker(sample_job.id, tmp_path)
        update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
        update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
        await worker.run(mock_page)
    db_session.expire_all()
        
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert records[0].status == RecordStatus.COMPLETED
    assert records[0].human_wait_seconds >= 0.5
    # The automated duration should be small (close to 0) since we didn't sleep in automation
    assert records[0].automated_duration_seconds < 0.5
