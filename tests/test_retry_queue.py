import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.automation.worker import Worker
from app.services.db_service import update_job_status, retry_failed_records
from app.automation.retry import get_backoff_delay, MAX_ATTEMPTS
from app.automation.navigation import NavigationError
from app.models.db import JobRecord
from app.models.location import LocationSelection
from app.services.db_service import create_job, upsert_discovered_records

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
    loc = LocationSelection(
        district_text="पुणे", district_value="1",
        taluka_text="मावळ", taluka_value="2",
        village_text="शिवाळी", village_value="3",
        division_text=None, division_value=None
    )
    job = create_job(db_session, loc)
    upsert_discovered_records(db_session, job.id, ["10/1", "20/2"])
    return job

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
@patch("app.automation.worker.apply_rate_limit", new_callable=AsyncMock)
async def test_transient_error_retry(
    mock_rate_limit, mock_backoff, mock_select, mock_prepare, mock_wait, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Simulate a transient network error on the first two attempts, success on third
    # For two records: R1 gets [Error, Error, None], R2 gets [None]
    mock_prepare.side_effect = [
        NavigationError("Network Issue 1", ErrorCategory.NETWORK_ERROR),
        NavigationError("Network Issue 2", ErrorCategory.NETWORK_ERROR),
        None, # Success R1
        None  # Success R2
    ]
    mock_save.return_value = MagicMock(created=True, size_bytes=100)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    
    await worker.run(mock_page)
    db_session.expire_all()
    
    db_session.refresh(sample_job)
    assert sample_job.status == JobStatus.COMPLETED
    assert sample_job.completed_records == 2
    assert mock_backoff.call_count == 2 # Backed off twice

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
async def test_fail_closed_error_no_retry(
    mock_backoff, mock_select, mock_prepare, mock_wait, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Simulate a structural failure
    mock_prepare.side_effect = NavigationError("Layout changed", ErrorCategory.PORTAL_LAYOUT_CHANGED)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    
    await worker.run(mock_page)
    db_session.expire_all()
    
    db_session.refresh(sample_job)
    assert sample_job.status == JobStatus.COMPLETED_WITH_ERRORS
    assert sample_job.completed_records == 0
    assert sample_job.failed_records == 2
    assert mock_backoff.call_count == 0

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.apply_backoff", new_callable=AsyncMock)
async def test_max_retries_exceeded(
    mock_backoff, mock_select, mock_prepare, mock_wait, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    # Simulate continuous timeout
    mock_prepare.side_effect = NavigationError("Timeout", ErrorCategory.TIMEOUT)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    
    await worker.run(mock_page)
    db_session.expire_all()
    
    db_session.refresh(sample_job)
    assert sample_job.status == JobStatus.COMPLETED_WITH_ERRORS
    # 2 records * (MAX_ATTEMPTS - 1) backoff calls
    assert mock_backoff.call_count == (MAX_ATTEMPTS - 1) * 2

def test_backoff_logic():
    assert get_backoff_delay(1) == 0.0
    delay2 = get_backoff_delay(2)
    assert 1.6 <= delay2 <= 2.4
    delay3 = get_backoff_delay(3)
    assert 3.2 <= delay3 <= 4.8

def test_retry_failed_records(db_session, sample_job):
    # Setup job and failed records
    sample_job.status = JobStatus.COMPLETED_WITH_ERRORS
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    for r in records:
        r.status = RecordStatus.FAILED
        r.last_error_code = ErrorCategory.TIMEOUT
        r.attempt_count = 3
    db_session.commit()
    
    # Call service
    count = retry_failed_records(db_session, sample_job.id)
    assert count == 2
    
    db_session.refresh(sample_job)
    assert sample_job.status == JobStatus.PAUSED
    
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    for r in records:
        assert r.status == RecordStatus.PENDING
        assert r.last_error_code is None
        assert r.attempt_count == 3
