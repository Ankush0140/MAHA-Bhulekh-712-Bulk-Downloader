from pydantic import BaseModel, Field, computed_field
from typing import Optional, List
from datetime import datetime
from app.models.enums import JobStatus, RecordStatus, ErrorCategory

class LocationItem(BaseModel):
    text: str
    value: str

class JobCreateRequest(BaseModel):
    # Division is application-side administrative metadata, NOT a portal value
    division_text: Optional[str] = None
    division_value: Optional[str] = None
    
    # District/Taluka/Village are actual Bhulekh portal metadata
    district_text: str
    district_value: str
    taluka_text: str
    taluka_value: str
    village_text: str
    village_value: str
    
class JobResponse(BaseModel):
    job_id: int = Field(..., alias="id")
    status: JobStatus
    
    # Division is application-side administrative metadata
    division_text: Optional[str] = None
    division_value: Optional[str] = None
    
    # Portal metadata
    district_text: str
    district_value: Optional[str] = None
    taluka_text: str
    taluka_value: Optional[str] = None
    village_text: str
    village_value: Optional[str] = None
    
    total: int = Field(alias="total_records", default=0)
    completed: int = Field(alias="completed_records", default=0)
    failed: int = Field(alias="failed_records", default=0)
    empty: int = Field(alias="empty_records", default=0)
    
    @computed_field
    @property
    def remaining(self) -> int:
        # Pydantic v2 computed properties during from_attributes usually need to be regular properties
        return max(0, self.total - (self.completed + self.failed + self.empty))
        
    pause_requested: bool = False
    automated_duration_seconds: float = Field(alias="automated_processing_seconds", default=0.0)
    human_wait_seconds: float = Field(default=0.0)
    
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    eta_seconds: Optional[int] = None
    eta_status: str = "insufficient_data"

    class Config:
        populate_by_name = True
        from_attributes = True

class RecordResponse(BaseModel):
    id: int
    survey_identifier_original: str
    status: RecordStatus
    attempt_count: int
    last_error_category: Optional[ErrorCategory] = Field(None, alias="last_error_code")
    last_error_message: Optional[str] = None
    output_relative_path: Optional[str] = None
    automated_duration_seconds: float
    human_wait_seconds: float

    class Config:
        populate_by_name = True
        from_attributes = True
