from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from sqlalchemy.orm import Session
from app.dependencies import get_db
from app.schemas import JobCreateRequest, JobResponse, RecordResponse
from app.services.db_service import (
    create_job, get_job, request_pause, resume_job, retry_failed_records,
    recover_stranded_job
)
from app.models.db import JobRecord
from app.models.location import LocationSelection
from app.services.job_manager import job_manager
from app.models.enums import JobStatus

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

@router.post("", response_model=JobResponse)
def api_create_job(req: JobCreateRequest, db: Session = Depends(get_db)):
    loc = LocationSelection(
        division_text=req.division_text,
        division_value=req.division_value,
        district_text=req.district_text,
        district_value=req.district_value,
        taluka_text=req.taluka_text,
        taluka_value=req.taluka_value,
        village_text=req.village_text,
        village_value=req.village_value
    )
    job = create_job(db, loc)
    return job

@router.get("/{job_id}", response_model=JobResponse)
def api_get_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job

@router.post("/{job_id}/start", response_model=JobResponse)
async def api_start_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status != JobStatus.CREATED:
        raise HTTPException(status_code=409, detail=f"Cannot start job in state {job.status.value}")
        
    started = job_manager.start_job(job_id)
    if not started:
        raise HTTPException(status_code=409, detail="Job is already actively running or queued")
        
    # Refresh to get potential state changes
    db.refresh(job)
    return job

@router.post("/{job_id}/pause", response_model=JobResponse)
def api_pause_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    success = request_pause(db, job_id)
    if not success:
        raise HTTPException(status_code=409, detail="Could not request pause for this job")
        
    db.refresh(job)
    return job

@router.post("/{job_id}/resume", response_model=JobResponse)
async def api_resume_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    success = resume_job(db, job_id)
    if not success:
        raise HTTPException(status_code=409, detail="Could not resume job")
        
    started = job_manager.start_job(job_id)
    if not started:
        raise HTTPException(status_code=409, detail="Another job is already running")
    db.refresh(job)
    return job

@router.post("/{job_id}/retry-failed", response_model=JobResponse)
def api_retry_failed_job(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    reset_count = retry_failed_records(db, job_id)
    if reset_count == 0:
        raise HTTPException(status_code=409, detail="No failed records to retry")
        
    db.refresh(job)
    return job

@router.post("/{job_id}/recover", response_model=JobResponse)
def api_recover_stranded_job(job_id: int, db: Session = Depends(get_db)):
    """
    FAILED -> PAUSED only when the persisted queue still holds unfinished work.
    Never starts the job; the user must explicitly resume afterwards.
    """
    from app.config import BASE_DIR as _BASE_DIR
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    assessment = recover_stranded_job(db, job_id, _BASE_DIR / "output")
    if not assessment.recoverable:
        raise HTTPException(status_code=409, detail=assessment.reason)

    db.refresh(job)
    return job

@router.get("/{job_id}/records", response_model=List[RecordResponse])
def api_get_job_records(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    records = db.query(JobRecord).filter(JobRecord.job_id == job_id).order_by(JobRecord.id.asc()).all()
    return records

from fastapi.responses import FileResponse
from pathlib import Path
from app.config import BASE_DIR
from app.services.report import generate_job_reports, _get_report_paths

@router.post("/{job_id}/reports")
def api_generate_reports(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    base_output_dir = BASE_DIR / "output"
    result = generate_job_reports(db, job_id, base_output_dir)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to generate reports")
    return result

@router.get("/{job_id}/reports/csv")
def api_get_report_csv(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    base_output_dir = BASE_DIR / "output"
    csv_path, _, _, _ = _get_report_paths(job, base_output_dir)
    
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Report not generated")
        
    return FileResponse(path=csv_path, filename=csv_path.name, media_type="text/csv")

@router.get("/{job_id}/reports/xlsx")
def api_get_report_xlsx(job_id: int, db: Session = Depends(get_db)):
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    base_output_dir = BASE_DIR / "output"
    _, xlsx_path, _, _ = _get_report_paths(job, base_output_dir)
    
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail="Report not generated")
        
    return FileResponse(path=xlsx_path, filename=xlsx_path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

