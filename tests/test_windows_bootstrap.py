"""
Regression tests for the Windows Uvicorn / Playwright bootstrap (Phase 12.8C-LITE).

Incident: with run.py using reload=True, Uvicorn on Windows selected
asyncio.SelectorEventLoop, and async_playwright().start() raised
NotImplementedError from asyncio.subprocess_exec (a job-level infrastructure
failure before the first record attempt).

These tests build the event loop through Uvicorn's own Config.get_loop_factory()
using the exact kwargs run.py passes to uvicorn.run(), so they exercise the
same loop-selection path as production. No network / Bhulekh access.
"""
import asyncio
import sys

import pytest
import uvicorn

import run


def _production_loop_factory():
    config = uvicorn.Config("app.main:app", **run.UVICORN_KWARGS)
    return config, config.get_loop_factory()


def test_run_py_disables_reload_and_extra_workers():
    assert run.UVICORN_KWARGS["reload"] is False
    assert run.UVICORN_KWARGS["workers"] == 1
    config, _ = _production_loop_factory()
    assert config.use_subprocess is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific loop selection")
def test_production_loop_is_proactor_on_windows():
    _, factory = _production_loop_factory()
    loop = factory()
    try:
        assert isinstance(loop, asyncio.ProactorEventLoop)
    finally:
        loop.close()


def test_production_loop_can_create_subprocess():
    """The capability Playwright needs: asyncio subprocess creation."""
    _, factory = _production_loop_factory()

    async def spawn():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "print('ok')",
            stdout=asyncio.subprocess.PIPE,
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.decode().strip()

    loop = factory()
    try:
        returncode, out = loop.run_until_complete(spawn())
    finally:
        loop.close()
    assert returncode == 0
    assert out == "ok"


@pytest.mark.skipif(sys.platform != "win32", reason="Documents the Windows failure mode")
def test_reload_mode_would_select_subprocess_incapable_loop():
    """Guards the root cause: reload=True gives SelectorEventLoop on Windows."""
    kwargs = dict(run.UVICORN_KWARGS, reload=True)
    config = uvicorn.Config("app.main:app", **kwargs)
    loop = config.get_loop_factory()()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
