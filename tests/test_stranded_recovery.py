import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.dependencies import get_db
from app.models.db import Base, Job, JobRecord
from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.services.db_service import (
    assess_stranded_job_recovery, recover_stranded_job, retry_failed_records, resume_job
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    Base.metadata.drop_all(engine)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


def _write_pdf(root, rel):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4\n%test\n")
    return rel


def _make_job(db, job_status, records):
    """records: list of (identifier, RecordStatus, attempt_count, output_rel or None)"""
    job = Job(district_text="D", taluka_text="T", village_text="V",
              status=job_status, total_records=len(records))
    db.add(job)
    db.commit()
    for ident, st, attempts, out in records:
        db.add(JobRecord(job_id=job.id, survey_identifier_original=ident,
                         survey_identifier_safe=ident.replace("/", "_"),
                         status=st, attempt_count=attempts, output_relative_path=out))
    db.commit()
    db.refresh(job)
    return job


def _records(db, job_id):
    db.expire_all()
    return {r.survey_identifier_original: r for r in
            db.query(JobRecord).filter(JobRecord.job_id == job_id).all()}


# A) FAILED job with 2 untouched PENDING records (the Job 10 shape)
def test_case_a_failed_all_pending_recovers_to_paused(db, tmp_path):
    job = _make_job(db, JobStatus.FAILED, [
        ("59/2/1", RecordStatus.PENDING, 0, None),
        ("299", RecordStatus.PENDING, 0, None),
    ])
    assert assess_stranded_job_recovery(db, job.id, tmp_path).recoverable is True

    result = recover_stranded_job(db, job.id, tmp_path)
    assert result.recoverable is True
    db.refresh(job)
    assert job.status == JobStatus.PAUSED
    assert job.completed_at is None
    recs = _records(db, job.id)
    for r in recs.values():
        assert r.status == RecordStatus.PENDING
        assert r.attempt_count == 0
        assert r.output_relative_path is None


# B) 1 COMPLETED with valid output + 1 PENDING
def test_case_b_completed_preserved_pending_kept(db, tmp_path):
    rel = _write_pdf(tmp_path, "job/a.pdf")
    job = _make_job(db, JobStatus.FAILED, [
        ("1", RecordStatus.COMPLETED, 1, rel),
        ("2", RecordStatus.PENDING, 0, None),
    ])
    recover_stranded_job(db, job.id, tmp_path)
    db.refresh(job)
    assert job.status == JobStatus.PAUSED
    assert job.completed_records == 1
    recs = _records(db, job.id)
    assert recs["1"].status == RecordStatus.COMPLETED
    assert recs["1"].output_relative_path == rel
    assert recs["1"].attempt_count == 1
    assert recs["2"].status == RecordStatus.PENDING


# C) RUNNING record without valid output -> PENDING; RUNNING with valid output -> COMPLETED
def test_case_c_running_normalized(db, tmp_path):
    rel = _write_pdf(tmp_path, "job/done.pdf")
    job = _make_job(db, JobStatus.FAILED, [
        ("1", RecordStatus.RUNNING, 1, None),
        ("2", RecordStatus.RUNNING, 1, "job/missing.pdf"),
        ("3", RecordStatus.RUNNING, 1, rel),
    ])
    recover_stranded_job(db, job.id, tmp_path)
    db.refresh(job)
    assert job.status == JobStatus.PAUSED
    recs = _records(db, job.id)
    assert recs["1"].status == RecordStatus.PENDING
    assert recs["2"].status == RecordStatus.PENDING
    assert recs["2"].output_relative_path is None
    # valid output is kept, never re-attempted (no duplicate output)
    assert recs["3"].status == RecordStatus.COMPLETED
    assert recs["3"].output_relative_path == rel
    assert all(r.attempt_count == 1 for r in recs.values())


# D) WAITING_FOR_CAPTCHA -> PENDING; no previous human session is referenced
def test_case_d_waiting_for_captcha_requires_fresh_verification(db, tmp_path):
    job = _make_job(db, JobStatus.FAILED, [
        ("1", RecordStatus.WAITING_FOR_CAPTCHA, 1, None),
        ("2", RecordStatus.PENDING, 0, None),
    ])
    job.current_record_id = 1
    job.pause_requested = True
    db.commit()

    recover_stranded_job(db, job.id, tmp_path)
    db.refresh(job)
    assert job.status == JobStatus.PAUSED
    assert job.current_record_id is None
    assert job.pause_requested is False
    recs = _records(db, job.id)
    assert recs["1"].status == RecordStatus.PENDING
    assert recs["1"].attempt_count == 1
    # No record is left in a state claiming an open human-verification page
    assert not any(r.status == RecordStatus.WAITING_FOR_CAPTCHA for r in recs.values())


# E) FAILED job with no resumable work -> rejected, nothing changed
@pytest.mark.parametrize("records", [
    [],  # discovery never produced a queue
    [("1", RecordStatus.FAILED, 3, None), ("2", RecordStatus.EMPTY, 1, None)],
])
def test_case_e_terminal_failed_job_not_recovered(db, tmp_path, records):
    job = _make_job(db, JobStatus.FAILED, records)
    result = recover_stranded_job(db, job.id, tmp_path)
    assert result.recoverable is False
    assert "Traceback" not in result.reason
    db.refresh(job)
    assert job.status == JobStatus.FAILED
    for r in _records(db, job.id).values():
        assert r.status in (RecordStatus.FAILED, RecordStatus.EMPTY)


def test_case_e_inconsistent_state_rejected(db, tmp_path):
    # COMPLETED record whose output is missing -> cannot be safely determined
    job = _make_job(db, JobStatus.FAILED, [
        ("1", RecordStatus.COMPLETED, 1, "job/gone.pdf"),
        ("2", RecordStatus.PENDING, 0, None),
    ])
    result = recover_stranded_job(db, job.id, tmp_path)
    assert result.recoverable is False
    assert "inconsistent" in result.reason
    assert str(tmp_path) not in result.reason
    db.refresh(job)
    assert job.status == JobStatus.FAILED

    # total_records mismatch
    job2 = _make_job(db, JobStatus.FAILED, [("9", RecordStatus.PENDING, 0, None)])
    job2.total_records = 5
    db.commit()
    assert recover_stranded_job(db, job2.id, tmp_path).recoverable is False
    db.refresh(job2)
    assert job2.status == JobStatus.FAILED


# F) Non-FAILED jobs are never touched
@pytest.mark.parametrize("job_status", [
    JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.PAUSED, JobStatus.CREATED
])
def test_case_f_non_failed_job_unchanged(db, tmp_path, job_status):
    job = _make_job(db, job_status, [("1", RecordStatus.PENDING, 0, None)])
    result = recover_stranded_job(db, job.id, tmp_path)
    assert result.recoverable is False
    db.refresh(job)
    assert job.status == job_status
    assert _records(db, job.id)["1"].status == RecordStatus.PENDING


# G) FAILED record mixed into queue stays FAILED; retry-failed remains authoritative
def test_case_g_failed_record_not_auto_retried(db, tmp_path):
    job = _make_job(db, JobStatus.FAILED, [
        ("1", RecordStatus.FAILED, 3, None),
        ("2", RecordStatus.PENDING, 0, None),
    ])
    recs = _records(db, job.id)
    recs["1"].last_error_code = ErrorCategory.TIMEOUT
    db.commit()

    recover_stranded_job(db, job.id, tmp_path)
    db.refresh(job)
    assert job.status == JobStatus.PAUSED
    assert job.failed_records == 1
    recs = _records(db, job.id)
    assert recs["1"].status == RecordStatus.FAILED
    assert recs["1"].last_error_code == ErrorCategory.TIMEOUT
    assert recs["2"].status == RecordStatus.PENDING

    # Only an explicit retry-failed resets it
    assert retry_failed_records(db, job.id) == 1
    assert _records(db, job.id)["1"].status == RecordStatus.PENDING


def test_resume_guard_still_rejects_failed_jobs(db):
    job = _make_job(db, JobStatus.FAILED, [("1", RecordStatus.PENDING, 0, None)])
    assert resume_job(db, job.id) is False
    db.refresh(job)
    assert job.status == JobStatus.FAILED


# ---- API: explicit recovery never starts the job, sanitized 409 ----

@pytest.fixture
def client(session_factory):
    def _override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()
    previous = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _override
    yield TestClient(app)
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous


def test_api_recover_pauses_without_starting(client, session_factory):
    s = session_factory()
    job = _make_job(s, JobStatus.FAILED, [
        ("1", RecordStatus.PENDING, 0, None), ("2", RecordStatus.PENDING, 0, None)
    ])
    job_id = job.id
    s.close()

    with patch("app.routes.jobs.job_manager.start_job") as mock_start:
        res = client.post(f"/api/jobs/{job_id}/recover")
        assert res.status_code == 200
        assert res.json()["status"] == "PAUSED"
        mock_start.assert_not_called()


def test_api_recover_rejects_terminal_with_sanitized_reason(client, session_factory):
    s = session_factory()
    job = _make_job(s, JobStatus.FAILED, [("1", RecordStatus.FAILED, 3, None)])
    job_id = job.id
    s.close()

    with patch("app.routes.jobs.job_manager.start_job") as mock_start:
        res = client.post(f"/api/jobs/{job_id}/recover")
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert "No unfinished records" in detail
        assert "Traceback" not in detail
        mock_start.assert_not_called()

    assert client.post("/api/jobs/99999/recover").status_code == 404
