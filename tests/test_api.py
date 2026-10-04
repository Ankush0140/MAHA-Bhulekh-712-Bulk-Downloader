import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from app.main import app
from app.dependencies import get_db
from app.models.db import Base, Job, JobRecord
from app.models.enums import JobStatus, RecordStatus
from app.services.location_service import LocationItem

from sqlalchemy.pool import StaticPool

# Setup test DB
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def mock_location_service():
    with patch("app.routes.locations.get_districts") as mock_districts, \
         patch("app.routes.locations.get_talukas") as mock_talukas, \
         patch("app.routes.locations.get_villages") as mock_villages:
        
        mock_districts.return_value = [LocationItem(text="Pune", value="1")]
        mock_talukas.return_value = [LocationItem(text="Maval", value="2")]
        mock_villages.return_value = [LocationItem(text="Shivali", value="3")]
        
        yield mock_districts, mock_talukas, mock_villages

@pytest.fixture
def mock_job_manager():
    with patch("app.routes.jobs.job_manager.start_job") as mock_start:
        mock_start.return_value = True
        yield mock_start

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_get_divisions():
    response = client.get("/api/locations/divisions")
    assert response.status_code == 200
    assert len(response.json()) == 6

def test_get_districts(mock_location_service):
    response = client.get("/api/locations/districts")
    assert response.status_code == 200
    assert response.json()[0]["text"] == "Pune"

def test_create_job():
    payload = {
        "district_text": "पुणे",
        "district_value": "1",
        "taluka_text": "मावळ",
        "taluka_value": "2",
        "village_text": "शिवाळी",
        "village_value": "3"
    }
    response = client.post("/api/jobs", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["district_text"] == "पुणे"
    assert data["status"] == "CREATED"
    assert data["id"] is not None

def test_get_nonexistent_job():
    response = client.get("/api/jobs/999")
    assert response.status_code == 404

def test_start_job(mock_job_manager):
    payload = {
        "district_text": "D", "district_value": "1",
        "taluka_text": "T", "taluka_value": "2",
        "village_text": "V", "village_value": "3"
    }
    res_create = client.post("/api/jobs", json=payload)
    job_id = res_create.json()["id"]

    res_start = client.post(f"/api/jobs/{job_id}/start")
    assert res_start.status_code == 200
    mock_job_manager.assert_called_once_with(job_id)
    
    # duplicate start rejected or allowed but not re-started
    with patch("app.routes.jobs.job_manager.start_job") as mock_start_dup:
        mock_start_dup.return_value = False
        res_start_dup = client.post(f"/api/jobs/{job_id}/start")
        assert res_start_dup.status_code == 409

def test_start_failed_job_rejected(mock_job_manager):
    db = TestingSessionLocal()
    job = Job(district_text="D", taluka_text="T", village_text="V", status=JobStatus.FAILED)
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    
    res = client.post(f"/api/jobs/{job_id}/start")
    assert res.status_code == 409
    assert "FAILED" in res.json()["detail"]
    mock_job_manager.assert_not_called()

def test_pause_and_resume_job():
    payload = {
        "district_text": "D", "district_value": "1",
        "taluka_text": "T", "taluka_value": "2",
        "village_text": "V", "village_value": "3"
    }
    res_create = client.post("/api/jobs", json=payload)
    job_id = res_create.json()["id"]

    res_pause = client.post(f"/api/jobs/{job_id}/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["pause_requested"] is True

    # manually set to paused for resume
    db = TestingSessionLocal()
    job = db.query(Job).filter_by(id=job_id).first()
    job.status = JobStatus.PAUSED
    db.commit()
    db.close()

    with patch("app.routes.jobs.job_manager.start_job") as mock_start:
        mock_start.return_value = True
        res_resume = client.post(f"/api/jobs/{job_id}/resume")
        assert res_resume.status_code == 200
        assert res_resume.json()["pause_requested"] is False

def test_retry_failed():
    db = TestingSessionLocal()
    job = Job(district_text="D", taluka_text="T", village_text="V", status=JobStatus.FAILED)
    db.add(job)
    db.commit()
    
    rec = JobRecord(job_id=job.id, survey_identifier_original="123", survey_identifier_safe="123", status=RecordStatus.FAILED, attempt_count=1)
    db.add(rec)
    db.commit()
    job_id = job.id
    db.close()

    res = client.post(f"/api/jobs/{job_id}/retry-failed")
    assert res.status_code == 200

    db = TestingSessionLocal()
    rec2 = db.query(JobRecord).first()
    assert rec2.status == RecordStatus.PENDING
    assert rec2.attempt_count == 1
    db.close()

def test_sse_endpoint():
    db = TestingSessionLocal()
    job = Job(district_text="D", taluka_text="T", village_text="V", status=JobStatus.COMPLETED)
    db.add(job)
    db.commit()
    job_id = job.id
    db.close()
    
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        lines = []
        for line in response.iter_lines():
            if line.startswith("event: "):
                lines.append(line)
                
        assert len(lines) > 0
        assert "event: completed" in lines
