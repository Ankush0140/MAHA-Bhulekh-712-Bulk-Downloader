import datetime
from typing import List, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from app.models.db import Job, JobRecord
from app.models.enums import JobStatus, RecordStatus, ErrorCategory
from app.models.location import LocationSelection
from app.services.filename import sanitize_filename_component

def create_job(db: Session, location: LocationSelection, search_mode: str = "NUMERIC") -> Job:
    job = Job(
        division_text=location.division_text,
        division_value=location.division_value,
        district_text=location.district_text,
        district_value=location.district_value,
        taluka_text=location.taluka_text,
        taluka_value=location.taluka_value,
        village_text=location.village_text,
        village_value=location.village_value,
        search_mode=search_mode,
        status=JobStatus.CREATED,
        created_at=datetime.datetime.utcnow(),
        updated_at=datetime.datetime.utcnow()
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

def get_job(db: Session, job_id: int) -> Optional[Job]:
    return db.query(Job).filter(Job.id == job_id).first()

def list_jobs(db: Session) -> List[Job]:
    return db.query(Job).order_by(Job.id.desc()).all()

VALID_JOB_TRANSITIONS = {
    JobStatus.CREATED: [JobStatus.DISCOVERING, JobStatus.FAILED, JobStatus.PAUSED],
    JobStatus.DISCOVERING: [JobStatus.WAITING_FOR_CAPTCHA, JobStatus.RUNNING, JobStatus.FAILED, JobStatus.PAUSED],
    JobStatus.WAITING_FOR_CAPTCHA: [JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.FAILED],
    JobStatus.RUNNING: [JobStatus.PAUSED, JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED, JobStatus.WAITING_FOR_CAPTCHA],
    JobStatus.PAUSED: [JobStatus.RUNNING, JobStatus.WAITING_FOR_CAPTCHA, JobStatus.FAILED, JobStatus.DISCOVERING],
    JobStatus.COMPLETED: [],
    JobStatus.COMPLETED_WITH_ERRORS: [],
    JobStatus.FAILED: [JobStatus.RUNNING, JobStatus.DISCOVERING] # Allow retry from failed if needed
}

def update_job_status(db: Session, job_id: int, status: JobStatus) -> Optional[Job]:
    job = get_job(db, job_id)
    if job:
        if status == job.status:
            return job
        if status not in VALID_JOB_TRANSITIONS.get(job.status, []):
            raise ValueError(f"Illegal state transition from {job.status} to {status}")
            
        job.status = status
        job.updated_at = datetime.datetime.utcnow()
        if status == JobStatus.RUNNING and job.started_at is None:
            job.started_at = datetime.datetime.utcnow()
        if status in [JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED]:
            job.completed_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(job)
    return job

def request_pause(db: Session, job_id: int) -> bool:
    job = get_job(db, job_id)
    if job and job.status not in [JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED]:
        job.pause_requested = True
        job.updated_at = datetime.datetime.utcnow()
        db.commit()
        return True
    return False

def resume_job(db: Session, job_id: int) -> bool:
    job = get_job(db, job_id)
    if job and job.status == JobStatus.PAUSED:
        job.pause_requested = False
        job.status = JobStatus.RUNNING
        job.updated_at = datetime.datetime.utcnow()
        db.commit()
        return True
    return False

def upsert_discovered_records(db: Session, job_id: int, survey_identifiers: List[str]) -> int:
    """
    Inserts newly discovered records. Ignores existing ones.
    Returns the number of new records inserted.
    """
    job = get_job(db, job_id)
    if not job:
        return 0

    inserted = 0
    for original in survey_identifiers:
        safe_survey = sanitize_filename_component(original)
        record = JobRecord(
            job_id=job_id,
            survey_identifier_original=original,
            survey_identifier_safe=safe_survey,
            status=RecordStatus.PENDING,
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        db.add(record)
        try:
            db.commit()
            inserted += 1
        except IntegrityError:
            db.rollback()  # Record already exists for this job
    
    # Update job totals
    total = db.query(JobRecord).filter(JobRecord.job_id == job_id).count()
    job.total_records = total
    db.commit()
    return inserted

def get_next_pending_record(db: Session, job_id: int) -> Optional[JobRecord]:
    return db.query(JobRecord).filter(
        JobRecord.job_id == job_id,
        JobRecord.status.in_([RecordStatus.PENDING, RecordStatus.WAITING_FOR_CAPTCHA])
    ).order_by(JobRecord.id.asc()).first()

def mark_record_waiting_for_captcha(db: Session, record_id: int) -> Optional[JobRecord]:
    record = db.query(JobRecord).filter(JobRecord.id == record_id).first()
    if record:
        record.status = RecordStatus.WAITING_FOR_CAPTCHA
        record.updated_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(record)
    return record

def mark_record_attempt_started(db: Session, record_id: int) -> Optional[JobRecord]:
    record = db.query(JobRecord).filter(JobRecord.id == record_id).first()
    if record:
        record.attempt_count += 1
        db.commit()
        db.refresh(record)
    return record

def mark_record_running(db: Session, record_id: int) -> Optional[JobRecord]:
    record = db.query(JobRecord).filter(JobRecord.id == record_id).first()
    if record:
        record.status = RecordStatus.RUNNING
        record.updated_at = datetime.datetime.utcnow()
        if record.started_at is None:
            record.started_at = datetime.datetime.utcnow()
        db.commit()
        db.refresh(record)
    return record

def mark_record_completed(db: Session, record_id: int, output_relative_path: str, pdf_size_bytes: int) -> Optional[JobRecord]:
    record = db.query(JobRecord).filter(JobRecord.id == record_id).first()
    if record:
        record.status = RecordStatus.COMPLETED
        record.updated_at = datetime.datetime.utcnow()
        record.completed_at = datetime.datetime.utcnow()
        record.output_relative_path = output_relative_path
        record.pdf_size_bytes = pdf_size_bytes
        db.commit()
        _update_job_counters(db, record.job_id)
        db.refresh(record)
    return record

def mark_record_failed(db: Session, record_id: int, error_code: ErrorCategory, error_message: str) -> Optional[JobRecord]:
    record = db.query(JobRecord).filter(JobRecord.id == record_id).first()
    if record:
        record.status = RecordStatus.FAILED
        record.updated_at = datetime.datetime.utcnow()
        record.completed_at = datetime.datetime.utcnow()
        record.last_error_code = error_code
        record.last_error_message = error_message
        db.commit()
        _update_job_counters(db, record.job_id)
        db.refresh(record)
    return record

def _update_job_counters(db: Session, job_id: int):
    job = get_job(db, job_id)
    if not job:
        return
        
    completed = db.query(JobRecord).filter(JobRecord.job_id == job_id, JobRecord.status == RecordStatus.COMPLETED).count()
    failed = db.query(JobRecord).filter(JobRecord.job_id == job_id, JobRecord.status == RecordStatus.FAILED).count()
    empty = db.query(JobRecord).filter(JobRecord.job_id == job_id, JobRecord.status == RecordStatus.EMPTY).count()
    
    job.completed_records = completed
    job.failed_records = failed
    job.empty_records = empty
    job.updated_at = datetime.datetime.utcnow()
    
    # Auto-complete job if all records are done
    if (completed + failed + empty) >= job.total_records and job.total_records > 0:
        if failed > 0:
            job.status = JobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = JobStatus.COMPLETED
        job.completed_at = datetime.datetime.utcnow()
        
    db.commit()

def release_human_wait_state(db: Session, job_id: int) -> bool:
    """
    Called when the browser holding a prepared CAPTCHA page is closing.
    WAITING_FOR_CAPTCHA must only describe a record whose official page is open
    for the human, so records go back to PENDING and the job becomes PAUSED.
    No CAPTCHA/mobile data is involved or stored.
    """
    changed = False
    waiting_records = db.query(JobRecord).filter(
        JobRecord.job_id == job_id,
        JobRecord.status == RecordStatus.WAITING_FOR_CAPTCHA
    ).all()
    for record in waiting_records:
        record.status = RecordStatus.PENDING
        record.updated_at = datetime.datetime.utcnow()
        changed = True

    job = get_job(db, job_id)
    if job and job.status == JobStatus.WAITING_FOR_CAPTCHA:
        job.status = JobStatus.PAUSED
        job.updated_at = datetime.datetime.utcnow()
        changed = True

    if changed:
        db.commit()
    return changed

def verify_output_pdf(output_path: Path) -> bool:
    """
    Checks if output file exists, is non-zero size, and starts with PDF signature.
    """
    if not output_path.exists() or not output_path.is_file():
        return False
        
    size = output_path.stat().st_size
    if size == 0:
        return False
        
    try:
        with open(output_path, "rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False
        return True
    except OSError:
        return False

def reconcile_interrupted_jobs(db: Session, output_root_dir: Path):
    """
    Startup reconciliation logic.
    For all RUNNING jobs, checks RUNNING records.
    If valid PDF found -> COMPLETED.
    Otherwise -> PENDING / WAITING_FOR_CAPTCHA.
    Jobs are put into PAUSED (resumable) state.
    """
    running_jobs = db.query(Job).filter(
        or_(
            Job.status == JobStatus.RUNNING,
            Job.status == JobStatus.DISCOVERING,
            Job.status == JobStatus.WAITING_FOR_CAPTCHA,
        )
    ).all()
    
    for job in running_jobs:
        job.status = JobStatus.PAUSED
        job.updated_at = datetime.datetime.utcnow()

        # The browser from the previous process is gone; no record can still be
        # awaiting human CAPTCHA entry.
        for waiting in db.query(JobRecord).filter(
            JobRecord.job_id == job.id,
            JobRecord.status == RecordStatus.WAITING_FOR_CAPTCHA
        ).all():
            waiting.status = RecordStatus.PENDING
            waiting.updated_at = datetime.datetime.utcnow()
        
        running_records = db.query(JobRecord).filter(JobRecord.job_id == job.id, JobRecord.status == JobStatus.RUNNING).all()
        for record in running_records:
            is_valid = False
            if record.output_relative_path:
                full_path = output_root_dir / record.output_relative_path
                if verify_output_pdf(full_path):
                    is_valid = True
                    
            if is_valid:
                record.status = RecordStatus.COMPLETED
                record.completed_at = datetime.datetime.utcnow()
            else:
                record.status = RecordStatus.PENDING
                record.output_relative_path = None
                record.pdf_size_bytes = None
                
            record.updated_at = datetime.datetime.utcnow()
            
        db.commit()
        _update_job_counters(db, job.id)

def retry_failed_records(db: Session, job_id: int) -> int:
    """
    Resets FAILED records to PENDING for a given job.
    Leaves attempt_count and historical timing intact.
    """
    failed_records = db.query(JobRecord).filter(
        JobRecord.job_id == job_id, 
        JobRecord.status == RecordStatus.FAILED
    ).all()
    
    reset_count = 0
    for record in failed_records:
        record.status = RecordStatus.PENDING
        record.completed_at = None
        record.last_error_code = None
        record.last_error_message = None
        record.updated_at = datetime.datetime.utcnow()
        reset_count += 1
        
    if reset_count > 0:
        job = get_job(db, job_id)
        if job and job.status in [JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED]:
            job.status = JobStatus.PAUSED
            job.updated_at = datetime.datetime.utcnow()
            
        db.commit()
        _update_job_counters(db, job_id)
        
    return reset_count


# ---------------------------------------------------------------------------
# Stranded FAILED job recovery
# ---------------------------------------------------------------------------
# A job-level infrastructure failure (e.g. browser startup failure) can mark a
# Job FAILED while its record queue is still intact. Recovery converts such a
# job to PAUSED only after validating the persisted queue. It never starts the
# job and never resets FAILED records (retry_failed_records stays authoritative).


class RecoveryAssessment:
    def __init__(self, recoverable: bool, reason: str, resumable_records: int = 0):
        self.recoverable = recoverable
        self.reason = reason
        self.resumable_records = resumable_records


def _record_has_valid_output(record: JobRecord, output_root_dir: Path) -> bool:
    if not record.output_relative_path:
        return False
    return verify_output_pdf(output_root_dir / record.output_relative_path)


def assess_stranded_job_recovery(db: Session, job_id: int, output_root_dir: Path) -> RecoveryAssessment:
    """
    Read-only predicate. A job is safely recoverable only when:
    - it exists and is FAILED
    - it has a persisted record queue matching total_records
    - every COMPLETED record still has a valid PDF output
    - every record status is known
    - at least one record represents unfinished work (PENDING,
      WAITING_FOR_CAPTCHA, or RUNNING without valid output)
    Returned reasons are sanitized (no paths, no tracebacks).
    """
    job = get_job(db, job_id)
    if not job:
        return RecoveryAssessment(False, "Job not found")
    if job.status != JobStatus.FAILED:
        return RecoveryAssessment(False, f"Only FAILED jobs can be recovered (current state {job.status.value})")

    records = db.query(JobRecord).filter(JobRecord.job_id == job_id).all()
    if not records:
        return RecoveryAssessment(False, "Job has no discovered records; nothing to recover")
    if job.total_records != len(records):
        return RecoveryAssessment(False, "Record count does not match job total; state is inconsistent")

    resumable = 0
    for record in records:
        if record.status == RecordStatus.COMPLETED:
            if not _record_has_valid_output(record, output_root_dir):
                return RecoveryAssessment(False, "A COMPLETED record has no valid output; state is inconsistent")
        elif record.status == RecordStatus.RUNNING:
            if not _record_has_valid_output(record, output_root_dir):
                resumable += 1
        elif record.status in (RecordStatus.PENDING, RecordStatus.WAITING_FOR_CAPTCHA):
            resumable += 1
        elif record.status in (RecordStatus.FAILED, RecordStatus.EMPTY):
            pass
        else:
            return RecoveryAssessment(False, "Unknown record state; state is inconsistent")

    if resumable == 0:
        return RecoveryAssessment(
            False,
            "No unfinished records remain; job is terminal (use retry-failed for FAILED records)"
        )
    return RecoveryAssessment(True, "Job has unfinished records and can be safely paused", resumable)


def recover_stranded_job(db: Session, job_id: int, output_root_dir: Path) -> RecoveryAssessment:
    """
    Converts a safely recoverable FAILED job to PAUSED. Does NOT start it.
    Record normalization follows the startup crash-reconciliation semantics:
      COMPLETED (valid output)  -> unchanged
      PENDING                   -> unchanged
      RUNNING + valid output    -> COMPLETED (no duplicate attempt)
      RUNNING without output    -> PENDING
      WAITING_FOR_CAPTCHA       -> PENDING (fresh human verification required;
                                   no previous browser/CAPTCHA session is reused)
      FAILED / EMPTY            -> unchanged
    """
    assessment = assess_stranded_job_recovery(db, job_id, output_root_dir)
    if not assessment.recoverable:
        return assessment

    now = datetime.datetime.utcnow()
    records = db.query(JobRecord).filter(JobRecord.job_id == job_id).all()
    for record in records:
        if record.status == RecordStatus.WAITING_FOR_CAPTCHA:
            record.status = RecordStatus.PENDING
            record.updated_at = now
        elif record.status == RecordStatus.RUNNING:
            if _record_has_valid_output(record, output_root_dir):
                record.status = RecordStatus.COMPLETED
                record.completed_at = now
            else:
                record.status = RecordStatus.PENDING
                record.output_relative_path = None
                record.pdf_size_bytes = None
            record.updated_at = now

    job = get_job(db, job_id)
    job.status = JobStatus.PAUSED
    job.pause_requested = False
    job.current_record_id = None
    job.completed_at = None
    job.updated_at = now
    db.commit()
    _update_job_counters(db, job_id)
    return assessment
