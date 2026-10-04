import os
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.models.db import setup_database, Job, JobRecord

def check_job_3():
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "data" / "app.db"
    
    SessionLocal = setup_database(db_path)
    db = SessionLocal()
    
    job = db.query(Job).filter(Job.id == 3).first()
    if not job:
        # Maybe the ID is different?
        job = db.query(Job).order_by(Job.id.desc()).first()
        
    print(f"Job ID: {job.id}")
    print(f"Job Status: {job.status}")
    print(f"Total Records: {job.total_records}")
    print(f"Completed Records: {job.completed_records}")
    print(f"Failed Records: {job.failed_records}")
    
    records = db.query(JobRecord).filter(JobRecord.job_id == job.id).all()
    for r in records:
        print(f"\nRecord: {r.survey_identifier_original}")
        print(f"Status: {r.status}")
        print(f"Output Relative Path: {r.output_relative_path}")
        print(f"Automated Duration: {r.automated_duration_seconds}s")
        print(f"Human Wait: {r.human_wait_seconds}s")
        
        # Verify output offline
        if r.output_relative_path:
            full_path = base_dir / "output" / r.output_relative_path
            print(f"\nPDF File Exists: {full_path.exists()}")
            if full_path.exists():
                size = full_path.stat().st_size
                print(f"PDF Size: {size} bytes")
                
                with open(full_path, "rb") as f:
                    header = f.read(5)
                print(f"PDF Header: {header}")

if __name__ == "__main__":
    check_job_3()
