import asyncio
import pytest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.db import Base, Job
from app.models.enums import JobStatus
from app.services.job_manager import JobManager

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.mark.asyncio
async def test_global_portal_concurrency():
    manager = JobManager()
    manager.active_tasks.clear()
    
    # Create two dummy jobs
    with TestingSessionLocal() as db:
        job1 = Job(district_text="D1", taluka_text="T1", village_text="V1", status=JobStatus.CREATED)
        job2 = Job(district_text="D2", taluka_text="T2", village_text="V2", status=JobStatus.CREATED)
        db.add_all([job1, job2])
        db.commit()
        id1 = job1.id
        id2 = job2.id

    # Mock _run_job_workflow to just sleep to simulate work
    async def fake_workflow(job_id):
        await asyncio.sleep(0.5)

    with patch.object(manager, "_run_job_workflow", side_effect=fake_workflow):
        # Start job 1
        res1 = manager.start_job(id1)
        assert res1 is True
        
        # Try to start job 2 while job 1 is running
        res2 = manager.start_job(id2)
        assert res2 is False # Should be rejected due to global concurrency limit
        
        # Wait for job 1 to finish
        await manager.active_tasks[id1]
        
        # Now job 1 is done, but our fake workflow didn't pop it from active_tasks because we mocked the whole method.
        # So we manually pop it
        manager.active_tasks.pop(id1)
        
        # Now job 2 should start successfully
        res3 = manager.start_job(id2)
        assert res3 is True
        await manager.active_tasks[id2]
        
@pytest.mark.asyncio
async def test_duplicate_start_race():
    manager = JobManager()
    manager.active_tasks.clear()
    
    with TestingSessionLocal() as db:
        job = Job(district_text="D", taluka_text="T", village_text="V", status=JobStatus.CREATED)
        db.add(job)
        db.commit()
        job_id = job.id

    async def fake_workflow(job_id):
        await asyncio.sleep(0.2)

    with patch.object(manager, "_run_job_workflow", side_effect=fake_workflow):
        # Since start_job is synchronous and we made our FastAPI route 'async def',
        # start_job will be executed on the main event loop thread without interruption
        # because it doesn't contain any 'await' yields during the check-and-insert.
        # We can still test this using asyncio to prove it is safe.
        
        async def call_start():
            # simulate any slight delay before calling
            return manager.start_job(job_id)
            
        results = await asyncio.gather(*(call_start() for _ in range(5)))
        
        # Only one should be True, the rest False
        assert results.count(True) == 1
        assert results.count(False) == 4
            
        await manager.active_tasks[job_id]
