import uvicorn
from app.config import HOST, PORT

# Production launch settings.
#
# reload MUST stay False (and workers must stay 1):
#
# 1. Windows / Playwright: when reload=True or workers>1, Uvicorn runs the
#    server in a child process and (uvicorn.loops.asyncio.asyncio_loop_factory)
#    deliberately selects asyncio.SelectorEventLoop on Windows. That loop does
#    not implement subprocess support, so async_playwright().start() fails with
#    NotImplementedError from asyncio.subprocess_exec. With reload=False Uvicorn
#    selects asyncio.ProactorEventLoop on Windows, which supports the
#    subprocesses Playwright needs to drive system Chrome. Uvicorn builds the
#    loop from its own factory, so setting an asyncio event-loop policy does not
#    override this choice.
#
# 2. Job safety: the StatReload file watcher restarts the server whenever any
#    .py file in the project changes (including scratch files), which cancels a
#    running job's worker and closes the human-verification browser mid-job.
#
# Non-Windows platforms already use the same loop either way, so this changes
# nothing there except disabling auto-reload.
UVICORN_KWARGS = {
    "host": HOST,
    "port": PORT,
    "reload": False,
    "workers": 1,
}

if __name__ == "__main__":
    uvicorn.run("app.main:app", **UVICORN_KWARGS)
