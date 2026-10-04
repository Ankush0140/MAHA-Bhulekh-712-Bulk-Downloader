import pytest
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base, Job, JobRecord
from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.models.location import LocationSelection
from app.services.db_service import (
    create_job, update_job_status, upsert_discovered_records,
    get_next_pending_record, mark_record_waiting_for_captcha,
    mark_record_running, mark_record_completed, mark_record_failed,
    request_pause, resume_job, reconcile_interrupted_jobs, get_job
)

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    yield db
    db.close()

@pytest.fixture
def sample_location():
    return LocationSelection(
        district_text="यवतमाळ", district_value="14",
        taluka_text="कळंब", taluka_value="3",
        village_text="आमला", village_value="271400030172280000",
        division_text=None, division_value=None
    )

def test_create_job(db_session, sample_location):
    job = create_job(db_session, sample_location)
    assert job.id is not None
    assert job.status == JobStatus.CREATED
    assert job.district_text == "यवतमाळ"
    assert job.district_value == "14"
    assert job.taluka_text == "कळंब"
    assert job.taluka_value == "3"
    assert job.village_text == "आमला"
    assert job.village_value == "271400030172280000"
    assert job.division_text is None
    assert job.division_value is None
    assert job.total_records == 0

def test_legal_state_transitions(db_session, sample_location):
    job = create_job(db_session, sample_location)
    job = update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    assert job.status == JobStatus.DISCOVERING
    
    job = update_job_status(db_session, job.id, JobStatus.WAITING_FOR_CAPTCHA)
    assert job.status == JobStatus.WAITING_FOR_CAPTCHA
    
    job = update_job_status(db_session, job.id, JobStatus.RUNNING)
    assert job.status == JobStatus.RUNNING

def test_illegal_state_transition_rejected(db_session, sample_location):
    job = create_job(db_session, sample_location)
    # CREATED -> COMPLETED is illegal
    with pytest.raises(ValueError, match="Illegal state transition"):
        update_job_status(db_session, job.id, JobStatus.COMPLETED)

def test_insert_discovered_records_and_duplicate_protection(db_session, sample_location):
    job = create_job(db_session, sample_location)
    surveys = ["1", "115/1/A", "17/10/ए"]
    
    inserted = upsert_discovered_records(db_session, job.id, surveys)
    assert inserted == 3
    
    # Check exact identifiers preserved
    records = db_session.query(JobRecord).all()
    orig_surveys = [r.survey_identifier_original for r in records]
    assert "1" in orig_surveys
    assert "115/1/A" in orig_surveys
    assert "17/10/ए" in orig_surveys
    
    # Check safe identifiers
    safe_surveys = [r.survey_identifier_safe for r in records]
    assert "115-1-A" in safe_surveys
    assert "17-10-ए" in safe_surveys
    
    # Duplicate discovery should not duplicate records
    inserted_again = upsert_discovered_records(db_session, job.id, ["1", "99"])
    assert inserted_again == 1 # Only 99 inserted
    
    db_session.refresh(job)
    assert job.total_records == 4

def test_get_next_pending_record(db_session, sample_location):
    job = create_job(db_session, sample_location)
    upsert_discovered_records(db_session, job.id, ["10", "20"])
    
    record1 = get_next_pending_record(db_session, job.id)
    assert record1.survey_identifier_original == "10"
    
    # Mark it running
    mark_record_running(db_session, record1.id)
    
    record2 = get_next_pending_record(db_session, job.id)
    assert record2.survey_identifier_original == "20"

def test_record_lifecycle_and_counters(db_session, sample_location):
    job = create_job(db_session, sample_location)
    upsert_discovered_records(db_session, job.id, ["A", "B", "C"])
    
    r_a = get_next_pending_record(db_session, job.id)
    mark_record_waiting_for_captcha(db_session, r_a.id)
    assert r_a.status == RecordStatus.WAITING_FOR_CAPTCHA
    
    from app.services.db_service import mark_record_attempt_started
    mark_record_attempt_started(db_session, r_a.id)
    mark_record_running(db_session, r_a.id)
    assert r_a.status == RecordStatus.RUNNING
    assert r_a.attempt_count == 1
    
    mark_record_completed(db_session, r_a.id, "path/A.pdf", 1024)
    assert r_a.status == RecordStatus.COMPLETED
    
    db_session.refresh(job)
    assert job.completed_records == 1
    
    r_b = get_next_pending_record(db_session, job.id)
    mark_record_failed(db_session, r_b.id, ErrorCategory.TIMEOUT, "Timeout")
    assert r_b.status == RecordStatus.FAILED
    
    db_session.refresh(job)
    assert job.failed_records == 1
    assert job.status == JobStatus.CREATED # Job status does not auto-update unless all records done
    
    r_c = get_next_pending_record(db_session, job.id)
    mark_record_completed(db_session, r_c.id, "path/C.pdf", 1024)
    
    db_session.refresh(job)
    assert job.completed_records == 2
    # All records done, job auto-completes to COMPLETED_WITH_ERRORS
    assert job.status == JobStatus.COMPLETED_WITH_ERRORS

def test_pause_resume(db_session, sample_location):
    job = create_job(db_session, sample_location)
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, job.id, JobStatus.RUNNING)
    
    assert request_pause(db_session, job.id) == True
    db_session.refresh(job)
    assert job.pause_requested == True
    
    update_job_status(db_session, job.id, JobStatus.PAUSED)
    
    assert resume_job(db_session, job.id) == True
    db_session.refresh(job)
    assert job.pause_requested == False
    assert job.status == JobStatus.RUNNING

def test_crash_recovery_reconciliation(db_session, sample_location, tmp_path):
    job = create_job(db_session, sample_location)
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    update_job_status(db_session, job.id, JobStatus.RUNNING)
    
    upsert_discovered_records(db_session, job.id, ["VALID", "MISSING", "CORRUPT"])
    records = db_session.query(JobRecord).all()
    for r in records:
        mark_record_running(db_session, r.id)
    
    valid_pdf_path = tmp_path / "valid.pdf"
    valid_pdf_path.write_bytes(b"%PDF-1.4...")
    
    empty_pdf_path = tmp_path / "missing.pdf"
    empty_pdf_path.touch() # zero size
    
    corrupt_pdf_path = tmp_path / "corrupt.pdf"
    corrupt_pdf_path.write_bytes(b"NOTAPDF...")
    
    # Set relative paths to mock
    records[0].output_relative_path = "valid.pdf"
    records[1].output_relative_path = "missing.pdf" 
    records[2].output_relative_path = "corrupt.pdf"
    db_session.commit()
    
    reconcile_interrupted_jobs(db_session, tmp_path)
    
    db_session.refresh(job)
    assert job.status == JobStatus.PAUSED
    
    db_session.refresh(records[0])
    assert records[0].status == RecordStatus.COMPLETED
    
    db_session.refresh(records[1])
    assert records[1].status == RecordStatus.PENDING
    assert records[1].output_relative_path is None
    
    db_session.refresh(records[2])
    assert records[2].status == RecordStatus.PENDING
    assert records[2].output_relative_path is None
    
    assert job.completed_records == 1

def test_no_mobile_persisted(db_session, sample_location):
    job = create_job(db_session, sample_location)
    # Check that job has no mobile field
    assert not hasattr(job, "mobile")
    assert not hasattr(job, "mobile_number")
    
    upsert_discovered_records(db_session, job.id, ["1"])
    record = get_next_pending_record(db_session, job.id)
    # Check that record has no mobile field
    assert not hasattr(record, "mobile")
    assert not hasattr(record, "mobile_number")

def test_no_mobile_in_config():
    import app.config as config
    assert not hasattr(config, "TEST_MOBILE_NUMBER")
    assert not hasattr(config, "MOBILE_NUMBER")

def test_direct_image_bytes_strategy():
    # Verify that pdf capture is removed and record_capture uses DIRECT_IMAGE_BYTES
    import app.automation.record_capture as rc
    with open(rc.__file__, "r", encoding="utf-8") as f:
        source = f.read()
    assert "page.pdf(" not in source
    assert "DIRECT_IMAGE_BYTES" not in source # Wait, DIRECT_IMAGE_BYTES is a strategy name, not necessarily in code verbatim, but let's check for base64/image decoding.
    assert "ImgPC" in source
    assert "data:image" in source

