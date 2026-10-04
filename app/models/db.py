import datetime
from pathlib import Path
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime, Enum as SQLEnum,
    ForeignKey, UniqueConstraint, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from app.models.enums import JobStatus, RecordStatus, ErrorCategory

Base = declarative_base()

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    division_text = Column(String, nullable=True)
    division_value = Column(String, nullable=True)
    district_text = Column(String, nullable=False)
    district_value = Column(String, nullable=True)
    taluka_text = Column(String, nullable=False)
    taluka_value = Column(String, nullable=True)
    village_text = Column(String, nullable=False)
    village_value = Column(String, nullable=True)
    
    search_mode = Column(String, default="NUMERIC")
    
    status = Column(SQLEnum(JobStatus), default=JobStatus.CREATED, nullable=False)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    total_records = Column(Integer, default=0)
    completed_records = Column(Integer, default=0)
    failed_records = Column(Integer, default=0)
    empty_records = Column(Integer, default=0)
    
    current_record_id = Column(Integer, nullable=True)
    
    pause_requested = Column(Boolean, default=False)
    
    last_error_code = Column(SQLEnum(ErrorCategory), nullable=True)
    last_error_message = Column(String, nullable=True)
    
    discovery_duration_seconds = Column(Float, default=0.0)
    automated_processing_seconds = Column(Float, default=0.0)
    human_wait_seconds = Column(Float, default=0.0)
    
    records = relationship("JobRecord", back_populates="job", cascade="all, delete-orphan")

class JobRecord(Base):
    __tablename__ = "job_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    
    survey_identifier_original = Column(String, nullable=False)
    survey_identifier_safe = Column(String, nullable=False)
    
    status = Column(SQLEnum(RecordStatus), default=RecordStatus.PENDING, nullable=False)
    
    attempt_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    output_relative_path = Column(String, nullable=True)
    
    last_error_code = Column(SQLEnum(ErrorCategory), nullable=True)
    last_error_message = Column(String, nullable=True)
    
    automated_duration_seconds = Column(Float, default=0.0)
    human_wait_seconds = Column(Float, default=0.0)
    
    source_mime = Column(String, nullable=True)
    source_width = Column(Integer, nullable=True)
    source_height = Column(Integer, nullable=True)
    source_size_bytes = Column(Integer, nullable=True)
    pdf_size_bytes = Column(Integer, nullable=True)
    
    job = relationship("Job", back_populates="records")
    
    __table_args__ = (
        UniqueConstraint('job_id', 'survey_identifier_original', name='_job_survey_uc'),
    )

def setup_database(db_path: Path) -> sessionmaker:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
