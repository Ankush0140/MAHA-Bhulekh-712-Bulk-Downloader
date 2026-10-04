import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.dependencies import get_db
from app.services.db_service import get_job
from app.models.db import JobRecord
from app.models.enums import JobStatus, RecordStatus

router = APIRouter(prefix="/api/jobs", tags=["progress"])

TOTAL_UNKNOWN_STATES = [JobStatus.CREATED, JobStatus.DISCOVERING]

def build_progress_payload(db: Session, job) -> tuple:
    """
    Build the (event_type, payload) pair for one SSE tick from persisted state only.
    """
    waiting_record = db.query(JobRecord).filter(
        JobRecord.job_id == job.id,
        JobRecord.status == RecordStatus.WAITING_FOR_CAPTCHA
    ).order_by(JobRecord.id.asc()).first()

    active_record = waiting_record or db.query(JobRecord).filter(
        JobRecord.job_id == job.id,
        JobRecord.status == RecordStatus.RUNNING
    ).order_by(JobRecord.id.asc()).first()

    # Human action is only real when an actual prepared record is awaiting the human.
    human_action_required = (
        job.status == JobStatus.WAITING_FOR_CAPTCHA and waiting_record is not None
    )

    # Before discovery has persisted the queue, the total is unknown, not zero.
    total_known = job.status not in TOTAL_UNKNOWN_STATES
    if total_known:
        total = job.total_records
        remaining = max(0, job.total_records - (job.completed_records + job.failed_records + job.empty_records))
    else:
        total = None
        remaining = None

    payload = {
        "job_id": job.id,
        "status": job.status.value,
        "total_known": total_known,
        "total": total,
        "completed": job.completed_records,
        "failed": job.failed_records,
        "empty": job.empty_records,
        "remaining": remaining,
        "current_record_id": active_record.id if active_record else None,
        "current_survey_identifier": active_record.survey_identifier_original if active_record else None,
        "current_record_status": active_record.status.value if active_record else None,
        "human_action_required": human_action_required,
        "pause_requested": job.pause_requested,
        "automated_duration_seconds": job.automated_processing_seconds,
        "human_wait_seconds": job.human_wait_seconds
    }

    if human_action_required:
        event_type = "human_action_required"
    elif job.status in [JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS]:
        event_type = "completed"
    elif job.status == JobStatus.PAUSED:
        event_type = "paused"
    elif job.status == JobStatus.FAILED:
        event_type = "error"
    else:
        event_type = "progress"

    return event_type, payload


async def progress_event_generator(request: Request, job_id: int, db: Session):
    """
    Generator that polls the database every second and yields SSE events.
    """
    while True:
        if await request.is_disconnected():
            break
            
        db.expire_all() # Ensure we get fresh data
        job = get_job(db, job_id)
        if not job:
            break
            
        event_type, payload = build_progress_payload(db, job)
            
        yield f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
        
        if job.status in [JobStatus.COMPLETED, JobStatus.COMPLETED_WITH_ERRORS, JobStatus.FAILED]:
            break
            
        await asyncio.sleep(1.0)


@router.get("/{job_id}/events")
async def stream_job_events(job_id: int, request: Request, db: Session = Depends(get_db)):
    # Verify job exists first
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    return StreamingResponse(
        progress_event_generator(request, job_id, db),
        media_type="text/event-stream"
    )
