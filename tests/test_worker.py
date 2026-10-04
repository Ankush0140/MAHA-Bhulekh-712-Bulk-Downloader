import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pathlib import Path

from app.automation.worker import Worker
from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.models.location import LocationSelection
from app.services.db_service import (
    create_job, upsert_discovered_records, get_job, 
    update_job_status, request_pause
)

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
    page.locator.return_value.evaluate = AsyncMock(return_value="2") # NUMERIC mode
    page.locator.return_value.inner_text = AsyncMock(return_value="")
    # For location verification, ensure inner_text includes what we expect
    def mock_inner_text():
        return "पुणे"
    page.locator.return_value.inner_text.side_effect = mock_inner_text
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
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
async def test_worker_successful_flow(
    mock_save_pdf, mock_extract, mock_wait, mock_prepare, mock_select, 
    db_session, sample_job, tmp_path, mock_page
):
    # Setup mocks
    mock_save_pdf.return_value = MagicMock(created=True, size_bytes=1000)
    
    # Run worker
    worker = Worker(sample_job.id, tmp_path)
    # Update job to discovering then running as if from real flow
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    
    # We only want to process ONE record then stop for this test, so we'll pause
    # Wait, the worker loop runs until no records. Let's let it process both.
    await worker.run(mock_page)
    db_session.expire_all()

    db_session.expire_all()
    job = get_job(db_session, sample_job.id)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_records == 2
    assert job.total_records == 2

    # Check that human timing was captured
    from app.models.db import JobRecord
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    assert len(records) == 2
    for r in records:
        assert r.status == RecordStatus.COMPLETED
        assert r.human_wait_seconds is not None
        assert r.automated_duration_seconds is not None
        assert r.output_relative_path is not None
        # Assert no mobile persisted
        assert not hasattr(r, "mobile")

@pytest.mark.asyncio
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_worker_pause_behavior(
    mock_wait, mock_prepare, mock_select, 
    db_session, sample_job, tmp_path, mock_page
):
    # Make select_location trigger a pause request to test mid-flight pause
    async def side_effect_select(*args, **kwargs):
        request_pause(db_session, sample_job.id)
    mock_select.side_effect = side_effect_select
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    
    await worker.run(mock_page)
    db_session.expire_all()
    
    job = get_job(db_session, sample_job.id)
    assert job.status == JobStatus.PAUSED
    assert job.completed_records == 0

@pytest.mark.asyncio
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
async def test_worker_location_mismatch_fails_closed(
    mock_select, db_session, sample_job, tmp_path, mock_page
):
    from app.automation.navigation import NavigationError
    mock_select.side_effect = NavigationError("Mismatch", ErrorCategory.LOCATION_SELECTION_MISMATCH)
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    
    # To prevent loop running for all records if all fail, wait, it will run for all.
    await worker.run(mock_page)
    db_session.expire_all()
    
    job = get_job(db_session, sample_job.id)
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS
    assert job.failed_records == 2
    
    from app.models.db import JobRecord
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    for r in records:
        assert r.status == RecordStatus.FAILED
        assert r.last_error_code == ErrorCategory.LOCATION_SELECTION_MISMATCH

@pytest.mark.asyncio
@patch("app.automation.worker.extract_record_image", new_callable=AsyncMock)
@patch("app.automation.worker.save_record_pdf")
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
async def test_failed_pdf_validation_does_not_complete(
    mock_select, mock_prepare, mock_wait, mock_save, mock_extract,
    db_session, sample_job, tmp_path, mock_page
):
    mock_save.return_value = MagicMock(created=False, error_message="Disk Full")
    
    worker = Worker(sample_job.id, tmp_path)
    update_job_status(db_session, sample_job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, sample_job.id, JobStatus.RUNNING)
    await worker.run(mock_page)
    db_session.expire_all()
    
    db_session.expire_all()
    from app.models.db import JobRecord
    records = db_session.query(JobRecord).filter(JobRecord.job_id == sample_job.id).all()
    for r in records:
        assert r.status == RecordStatus.FAILED
        assert r.last_error_code == ErrorCategory.PDF_WRITE_ERROR
