import pytest_asyncio
import pytest
from playwright.async_api import async_playwright
import json

HTML_MOCK = """
<!DOCTYPE html>
<html>
<body>
    <select id="divisionSelect"><option value="1" selected>Div 1</option></select>
    <select id="districtSelect"><option value="1" selected>Dist 1</option></select>
    <select id="talukaSelect"><option value="1" selected>Taluka 1</option></select>
    <select id="villageSelect"><option value="1" selected>Village 1</option></select>
    <button id="startBtn">Start Download</button>
    
    <div id="apiErrorNotice" style="display:none;"></div>
    <div id="captchaNotice" style="display:none;"></div>
    <div id="jobSection" style="display:none;"></div>
    <span id="activeJobIdText"></span>
    <span id="activeJobLocationText"></span>
    <strong id="jobStatusBadge"></strong>
    <span id="jobEta"></span>
    <div id="progressBar"></div>
    <span id="progressText"></span>
    <span id="statTotal"></span>
    <span id="statCompleted"></span>
    <span id="statFailed"></span>
    <span id="statRemaining"></span>
    <button id="pauseBtn"></button>
    <button id="resumeBtn"></button>
    <button id="retryBtn"></button>
    <div id="completionMessage"></div>
    <div id="recordSection"></div>
    <span id="currentRecordId"></span>
    <span id="currentRecordStatus"></span>
    <div id="failedRecordsSection"></div>
    <div id="failedTableBody"></div>
    <div id="reportControls"></div>
    <a id="downloadCsvBtn"></a>
    <a id="downloadXlsxBtn"></a>
    <button id="generateReportsBtn"></button>
    
    <script>
        // Mocks
        window.apiResponses = {};
        window.fetch = async (url, options) => {
            if (window.apiResponses[url]) {
                const res = window.apiResponses[url];
                if (res.error) {
                    return { ok: false, status: 500, json: async () => ({detail: res.error}) };
                }
                return { ok: true, json: async () => res.data };
            }
            return { ok: true, json: async () => ({}) };
        };
        
        class MockEventSource {
            constructor(url) {
                this.url = url;
                this.readyState = 1;
                this.listeners = {};
                window.lastEventSource = this;
            }
            addEventListener(type, cb) {
                this.listeners[type] = cb;
            }
            close() {
                this.readyState = 2;
                this.closed = true;
            }
            emit(type, data) {
                if (this.listeners[type]) this.listeners[type]({data: JSON.stringify(data)});
            }
        }
        window.EventSource = MockEventSource;
    </script>
    <script src="app.js"></script>
</body>
</html>
"""

@pytest_asyncio.fixture
async def page_with_js(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()
        
        with open("app/static/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()
            
        test_dir = tmp_path / "test_ui"
        test_dir.mkdir(exist_ok=True)
        
        with open(test_dir / "app.js", "w", encoding="utf-8") as f:
            f.write(app_js)
            
        with open(test_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(HTML_MOCK)
            
        await page.goto(f"file://{test_dir}/index.html")
        yield page
        await browser.close()

@pytest.mark.asyncio
async def test_successful_start_updates_current_job(page_with_js):
    page = page_with_js
    await page.evaluate('''() => {
        window.apiResponses['/api/jobs'] = {data: {id: 99}};
        window.apiResponses['/api/jobs/99/start'] = {data: {}};
        window.apiResponses['/api/jobs/99'] = {data: {id: 99, status: 'CREATED', district_text: 'D', taluka_text: 'T', village_text: 'V'}};
    }''')
    await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
    await page.click('#startBtn')
    await page.wait_for_timeout(100)
    current_job_id = await page.evaluate("localStorage.getItem('maha_job_id')")
    assert current_job_id == "99"
    active_id_text = await page.inner_text('#activeJobIdText')
    assert "Job #99" in active_id_text

@pytest.mark.asyncio
async def test_failed_start_does_not_overwrite_localstorage(page_with_js):
    page = page_with_js
    await page.evaluate("localStorage.setItem('maha_job_id', '88')")
    await page.evaluate('''() => {
        window.apiResponses['/api/jobs'] = {data: {id: 99}};
        window.apiResponses['/api/jobs/99/start'] = {error: 'Concurrency error'};
    }''')
    await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
    await page.click('#startBtn')
    await page.wait_for_timeout(100)
    current_job_id = await page.evaluate("localStorage.getItem('maha_job_id')")
    assert current_job_id == "88"
    is_disabled = await page.evaluate("document.getElementById('startBtn').disabled")
    assert is_disabled is False

@pytest.mark.asyncio
async def test_stale_sse_cannot_mutate_current_job(page_with_js):
    page = page_with_js
    await page.evaluate('''() => {
        window.apiResponses['/api/jobs'] = {data: {id: 99}};
        window.apiResponses['/api/jobs/99/start'] = {data: {}};
        window.apiResponses['/api/jobs/99'] = {data: {id: 99, status: 'RUNNING', total_records: 10, district_text: 'D'}};
    }''')
    await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
    await page.click('#startBtn')
    await page.wait_for_timeout(100)
    await page.evaluate('''() => {
        const oldSseData = {job_id: 88, status: 'COMPLETED', total: 769, completed: 769};
        window.lastEventSource.emit('progress', oldSseData);
    }''')
    await page.wait_for_timeout(50)
    active_id_text = await page.inner_text('#activeJobIdText')
    assert "Job #99" in active_id_text
    total_text = await page.inner_text('#statTotal')
    assert total_text == "10"

@pytest.mark.asyncio
async def test_new_start_closes_previous_eventsource(page_with_js):
    page = page_with_js
    await page.evaluate('''() => {
        window.apiResponses['/api/jobs'] = {data: {id: 10}};
        window.apiResponses['/api/jobs/10/start'] = {data: {}};
        window.apiResponses['/api/jobs/10'] = {data: {id: 10, status: 'RUNNING'}};
    }''')
    await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
    await page.click('#startBtn')
    await page.wait_for_timeout(50)
    await page.evaluate('''() => {
        window.firstEventSource = window.lastEventSource;
        window.apiResponses['/api/jobs'] = {data: {id: 11}};
        window.apiResponses['/api/jobs/11/start'] = {data: {}};
        window.apiResponses['/api/jobs/11'] = {data: {id: 11, status: 'RUNNING'}};
    }''')
    await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
    await page.click('#startBtn')
    await page.wait_for_timeout(50)
    first_closed = await page.evaluate("window.firstEventSource.closed")
    assert first_closed is True

@pytest.mark.asyncio
async def test_restored_job_does_not_disable_start_button_if_selection_valid(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel="chrome")
        context = await browser.new_context()
        page = await context.new_page()
        
        with open("app/static/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()
            
        test_dir = tmp_path / "test_ui2"
        test_dir.mkdir(exist_ok=True)
        
        with open(test_dir / "app.js", "w", encoding="utf-8") as f:
            f.write(app_js)
            
        with open(test_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(HTML_MOCK)
            
        # Add init script to set localStorage and apiResponses BEFORE load!
        await page.add_init_script("""
            localStorage.setItem('maha_job_id', '88');
            window.apiResponses = {'/api/jobs/88': {data: {id: 88, status: 'RUNNING'}}};
        """)
        
        await page.goto(f"file://{test_dir}/index.html")
        await page.wait_for_timeout(100)
        
        await page.evaluate('document.getElementById("villageSelect").dispatchEvent(new Event("change"))')
        
        await page.evaluate("""() => {
            if (window.lastEventSource) {
                window.lastEventSource.emit('progress', {job_id: 88, status: 'RUNNING'});
            }
        }""")
        
        is_disabled = await page.evaluate("document.getElementById('startBtn').disabled")
        assert is_disabled is False
        await browser.close()
