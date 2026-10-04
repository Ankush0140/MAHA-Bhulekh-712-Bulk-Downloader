"""
Phase 12.2 — human CAPTCHA window regression tests.

A. DISCOVERING never presents as WAITING_FOR_CAPTCHA; total/remaining are unknown, not 0.
B. WAITING_FOR_CAPTCHA (human_action_required) corresponds to an actual persisted JobRecord.
C. The browser/page holding the prepared record stays open for the whole human wait.
D. Human wait has no five-minute automation timeout.
E. Pause during human wait remains safely detectable.
F. No CAPTCHA / mobile value is persisted or typed by automation.
Plus: production job workflow launches visible system Chrome, and the
WAITING_FOR_CAPTCHA state never outlives the browser.
"""
import inspect
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.db import Job, JobRecord
from app.models.enums import JobStatus, RecordStatus
from app.services.db_service import (
    create_job, upsert_discovered_records, update_job_status, get_job,
    mark_record_waiting_for_captcha, release_human_wait_state, reconcile_interrupted_jobs,
)
from app.routes.progress import build_progress_payload
from app.automation.worker import Worker
from app.automation import navigation
from app.automation.navigation import wait_for_human_result, PauseRequested
from app.automation import selectors


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.models.db import Base
    from app.dependencies import SessionLocal
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal.configure(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def job(db_session):
    from app.models.location import LocationSelection
    loc = LocationSelection(
        division_text="Pune Division", division_value="pune",
        district_text="पुणे", district_value="25",
        taluka_text="आंबेगाव", taluka_value="2",
        village_text="अडिवरे", village_value="272500020302910000",
    )
    return create_job(db_session, loc)


@pytest.fixture
def mock_page():
    page = AsyncMock()
    page.locator = MagicMock()
    page.locator.return_value.evaluate = AsyncMock(return_value="2")
    page.locator.return_value.inner_text = AsyncMock(return_value="x")
    page.locator.return_value.fill = AsyncMock()
    return page


# ---------------------------------------------------------------- A
def test_discovering_is_not_waiting_for_captcha_and_total_unknown(db_session, job):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    db_session.refresh(job)

    event_type, payload = build_progress_payload(db_session, job)

    assert event_type == "progress"
    assert payload["status"] == "DISCOVERING"
    assert payload["human_action_required"] is False
    assert payload["total_known"] is False
    assert payload["total"] is None
    assert payload["remaining"] is None  # not a misleading 0


def test_total_and_remaining_come_from_persisted_queue_after_discovery(db_session, job):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1", "2", "3"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)
    db_session.refresh(job)

    _, payload = build_progress_payload(db_session, job)
    assert payload["total_known"] is True
    assert payload["total"] == 3
    assert payload["remaining"] == 3


# ---------------------------------------------------------------- B
def test_waiting_status_without_persisted_waiting_record_is_not_human_action(db_session, job):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1"])
    update_job_status(db_session, job.id, JobStatus.WAITING_FOR_CAPTCHA)  # no record prepared
    db_session.refresh(job)

    event_type, payload = build_progress_payload(db_session, job)
    assert payload["human_action_required"] is False
    assert event_type != "human_action_required"


def test_waiting_for_captcha_corresponds_to_actual_record(db_session, job):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1", "2"])
    rec = db_session.query(JobRecord).filter(JobRecord.job_id == job.id).order_by(JobRecord.id).first()
    mark_record_waiting_for_captcha(db_session, rec.id)
    update_job_status(db_session, job.id, JobStatus.WAITING_FOR_CAPTCHA)
    db_session.refresh(job)

    event_type, payload = build_progress_payload(db_session, job)
    assert event_type == "human_action_required"
    assert payload["human_action_required"] is True
    assert payload["current_record_id"] == rec.id
    assert payload["current_survey_identifier"] == "1"
    assert payload["current_record_status"] == "WAITING_FOR_CAPTCHA"
    assert payload["total"] == 2


@pytest.mark.asyncio
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
async def test_worker_persists_waiting_only_after_record_prepared(
    mock_select, mock_prepare, db_session, job, mock_page, tmp_path
):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["7"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)

    observed = {}

    async def fake_prepare(page, survey, *args, **kwargs):
        db_session.expire_all()
        observed["status_during_prepare"] = get_job(db_session, job.id).status
        observed["survey"] = survey

    mock_prepare.side_effect = fake_prepare

    async def fake_wait(page, job_id, timeout_ms, target_title=None):
        db_session.expire_all()
        observed["status_during_wait"] = get_job(db_session, job_id).status
        observed["record_during_wait"] = db_session.query(JobRecord).filter(JobRecord.job_id == job_id).first().status
        get_job(db_session, job_id).pause_requested = True
        db_session.commit()
        raise PauseRequested()

    with patch("app.automation.worker.wait_for_human_result", side_effect=fake_wait):
        await Worker(job.id, tmp_path).run(mock_page)

    assert observed["status_during_prepare"] == JobStatus.RUNNING
    assert observed["survey"] == "7"
    assert observed["status_during_wait"] == JobStatus.WAITING_FOR_CAPTCHA
    assert observed["record_during_wait"] == RecordStatus.WAITING_FOR_CAPTCHA
    mock_page.bring_to_front.assert_awaited()


# ---------------------------------------------------------------- C
@pytest.mark.asyncio
async def test_job_workflow_keeps_browser_open_during_human_wait(db_session, job):
    from app.services import job_manager as jm_module
    from app.services.job_manager import JobManager

    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)

    browser = AsyncMock()
    context = AsyncMock()
    page = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    launcher = AsyncMock(return_value=(browser, context))

    pw_starter = MagicMock()
    pw_starter.start = AsyncMock(return_value=AsyncMock())

    seen = {}

    async def fake_worker_run(self, run_page):
        # Simulate the record being prepared and the human wait in progress.
        rec = db_session.query(JobRecord).filter(JobRecord.job_id == job.id).first()
        mark_record_waiting_for_captcha(db_session, rec.id)
        update_job_status(db_session, job.id, JobStatus.WAITING_FOR_CAPTCHA)
        seen["same_page"] = run_page is page
        seen["browser_closed_during_wait"] = browser.close.await_count
        seen["context_closed_during_wait"] = context.close.await_count
        seen["page_closed_during_wait"] = page.close.await_count
        # human pauses -> worker returns

    manager = JobManager()
    with patch.object(jm_module, "launch_human_workflow_browser", launcher), \
         patch.object(jm_module, "async_playwright", return_value=pw_starter), \
         patch.object(Worker, "run", fake_worker_run):
        await manager._run_job_workflow(job.id)

    assert seen["same_page"] is True
    assert seen["browser_closed_during_wait"] == 0
    assert seen["context_closed_during_wait"] == 0
    assert seen["page_closed_during_wait"] == 0
    # Closed exactly once, only after the worker returned.
    assert browser.close.await_count == 1

    # WAITING_FOR_CAPTCHA must not outlive the browser.
    db_session.expire_all()
    assert get_job(db_session, job.id).status == JobStatus.PAUSED
    rec = db_session.query(JobRecord).filter(JobRecord.job_id == job.id).first()
    assert rec.status == RecordStatus.PENDING


def test_production_workflow_uses_visible_system_chrome():
    from app.automation import browser as browser_mod
    from app.services import job_manager as jm_module

    assert browser_mod.HUMAN_WORKFLOW_CHANNEL == "chrome"
    assert browser_mod.HUMAN_WORKFLOW_HEADLESS is False
    src = inspect.getsource(jm_module.JobManager._run_job_workflow)
    assert "launch_human_workflow_browser(" in src
    assert "HEADLESS" not in src


@pytest.mark.asyncio
async def test_human_workflow_launcher_passes_chrome_headful(monkeypatch):
    from app.automation import browser as browser_mod
    monkeypatch.setenv("HEADLESS", "true")  # must not influence the human workflow
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=AsyncMock())
    await browser_mod.launch_human_workflow_browser(pw)
    kwargs = pw.chromium.launch.await_args.kwargs
    assert kwargs == {"headless": False, "channel": "chrome"}


def test_restart_reconciles_waiting_job_without_browser(db_session, job, tmp_path):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1", "2"])
    rec = db_session.query(JobRecord).filter(JobRecord.job_id == job.id).first()
    mark_record_waiting_for_captcha(db_session, rec.id)
    update_job_status(db_session, job.id, JobStatus.WAITING_FOR_CAPTCHA)

    reconcile_interrupted_jobs(db_session, tmp_path)
    db_session.expire_all()

    assert get_job(db_session, job.id).status == JobStatus.PAUSED
    assert all(r.status == RecordStatus.PENDING for r in db_session.query(JobRecord).filter(JobRecord.job_id == job.id))
    assert get_job(db_session, job.id).total_records == 2  # history kept


def test_release_human_wait_state_is_noop_for_other_states(db_session, job):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)
    assert release_human_wait_state(db_session, job.id) is False
    assert get_job(db_session, job.id).status == JobStatus.RUNNING


# ---------------------------------------------------------------- D
def test_human_wait_has_no_five_minute_timeout():
    default = inspect.signature(wait_for_human_result).parameters["timeout_ms"].default
    assert default >= 3_600_000
    assert default != 300_000


@pytest.mark.asyncio
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
@patch("app.automation.worker.wait_for_human_result", new_callable=AsyncMock)
async def test_worker_requests_long_human_wait(mock_wait, mock_select, mock_prepare, db_session, job, mock_page, tmp_path):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)
    mock_wait.side_effect = PauseRequested()
    get_job(db_session, job.id).pause_requested = True  # stop the loop after one record
    db_session.commit()
    get_job(db_session, job.id).pause_requested = False
    db_session.commit()

    async def wait_then_pause(page, job_id, timeout_ms):
        get_job(db_session, job_id).pause_requested = True
        db_session.commit()
        raise PauseRequested()
    mock_wait.side_effect = wait_then_pause

    await Worker(job.id, tmp_path).run(mock_page)
    assert mock_wait.await_args.kwargs["timeout_ms"] >= 3_600_000


# ---------------------------------------------------------------- E
@pytest.mark.asyncio
async def test_pause_during_human_wait_detected(db_session, job, mock_page):
    mock_page.evaluate = AsyncMock(return_value=False)
    get_job(db_session, job.id).pause_requested = True
    db_session.commit()
    with pytest.raises(PauseRequested):
        await wait_for_human_result(mock_page, job.id, timeout_ms=3_600_000)


# ---------------------------------------------------------------- F
def test_no_captcha_or_mobile_columns_persisted():
    for model in (Job, JobRecord):
        cols = [c.name.lower() for c in model.__table__.columns]
        for forbidden in ("captcha", "mobile", "otp", "phone", "cookie", "viewstate"):
            assert not any(forbidden in c for c in cols), f"{model.__name__} has {forbidden} column"


def test_automation_never_touches_mobile_or_captcha_fields():
    import app.automation.worker as worker_mod
    import app.services.job_manager as jm_mod
    for mod in (navigation, worker_mod, jm_mod):
        src = inspect.getsource(mod)
        assert "MOBILE_INPUT" not in src
        assert "CAPTCHA_INPUT" not in src
        assert "SUBMIT_BUTTON" not in src
        assert selectors.MOBILE_INPUT not in src
        assert selectors.CAPTCHA_INPUT not in src
        assert selectors.SUBMIT_BUTTON not in src


@pytest.mark.asyncio
@patch("app.automation.worker.prepare_record", new_callable=AsyncMock)
@patch("app.automation.worker.select_location", new_callable=AsyncMock)
async def test_worker_does_not_fill_anything_during_human_wait(mock_select, mock_prepare, db_session, job, mock_page, tmp_path):
    update_job_status(db_session, job.id, JobStatus.DISCOVERING)
    upsert_discovered_records(db_session, job.id, ["1"])
    update_job_status(db_session, job.id, JobStatus.RUNNING)

    async def wait_then_pause(page, job_id, timeout_ms):
        get_job(db_session, job_id).pause_requested = True
        db_session.commit()
        raise PauseRequested()

    with patch("app.automation.worker.wait_for_human_result", side_effect=wait_then_pause):
        await Worker(job.id, tmp_path).run(mock_page)

    mock_page.fill.assert_not_called()
    mock_page.type.assert_not_called()
    mock_page.locator.return_value.fill.assert_not_called()
    mock_page.click.assert_not_called()
