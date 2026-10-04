document.addEventListener('DOMContentLoaded', () => {
    console.log('MAHA Bhulekh 7/12 Bulk Downloader initialized.');

    // State
    let currentJobId = localStorage.getItem('maha_job_id');
    let eventSource = null;
    let lastRestJob = null;     // last full JobResponse (keeps ETA fields between SSE ticks)
    let lastFailedKey = null;   // avoids refetching failed records every SSE tick

    // Elements
    const divisionSelect = document.getElementById('divisionSelect');
    const districtSelect = document.getElementById('districtSelect');
    const talukaSelect = document.getElementById('talukaSelect');
    const villageSelect = document.getElementById('villageSelect');
    const startBtn = document.getElementById('startBtn');

    const apiErrorNotice = document.getElementById('apiErrorNotice');
    const captchaNotice = document.getElementById('captchaNotice');

    const jobSection = document.getElementById('jobSection');
    const activeJobIdText = document.getElementById('activeJobIdText');
    const activeJobLocationText = document.getElementById('activeJobLocationText');
    const jobStatusBadge = document.getElementById('jobStatusBadge');
    const jobEta = document.getElementById('jobEta');
    const progressBar = document.getElementById('progressBar');
    const progressText = document.getElementById('progressText');

    const statTotal = document.getElementById('statTotal');
    const statCompleted = document.getElementById('statCompleted');
    const statFailed = document.getElementById('statFailed');
    const statRemaining = document.getElementById('statRemaining');

    const pauseBtn = document.getElementById('pauseBtn');
    const resumeBtn = document.getElementById('resumeBtn');
    const retryBtn = document.getElementById('retryBtn');
    const completionMessage = document.getElementById('completionMessage');

    const recordSection = document.getElementById('recordSection');
    const currentRecordId = document.getElementById('currentRecordId');
    const currentRecordStatus = document.getElementById('currentRecordStatus');

    const failedRecordsSection = document.getElementById('failedRecordsSection');
    const failedTableBody = document.getElementById('failedTableBody');

    const reportControls = document.getElementById('reportControls');
    const generateReportsBtn = document.getElementById('generateReportsBtn');
    const downloadCsvBtn = document.getElementById('downloadCsvBtn');
    const downloadXlsxBtn = document.getElementById('downloadXlsxBtn');

    // API Helper
    async function apiRequest(url, options = {}) {
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                let errorMsg = `HTTP Error ${response.status}`;
                try {
                    const errorData = await response.json();
                    if (errorData.detail) {
                        errorMsg = typeof errorData.detail === 'string' ? errorData.detail : JSON.stringify(errorData.detail);
                    }
                } catch (e) {}
                throw new Error(errorMsg);
            }
            return await response.json();
        } catch (error) {
            showApiError(error.message);
            throw error;
        }
    }

    function showApiError(msg) {
        apiErrorNotice.textContent = msg;
        apiErrorNotice.style.display = 'block';
        setTimeout(() => {
            apiErrorNotice.style.display = 'none';
        }, 5000);
    }

    // Initialization
    init();

    async function init() {
        await loadDivisions();
        
        if (currentJobId) {
            await restoreJob(currentJobId);
        }
    }

    // Cascading Selectors
    async function loadDivisions() {
        try {
            const divisions = await apiRequest('/api/locations/divisions');
            populateSelect(divisionSelect, divisions, 'Select Division...');
        } catch (error) {
            console.error("Failed to load divisions", error);
            showApiError('Failed to load divisions.');
        }
    }

    async function loadDistricts(divisionVal) {
        try {
            let url = '/api/locations/districts';
            if (divisionVal) {
                url += `?division_value=${encodeURIComponent(divisionVal)}`;
            }
            const districts = await apiRequest(url);
            populateSelect(districtSelect, districts, 'Select District...');
            districtSelect.disabled = false;
        } catch (error) {
            console.error("Failed to load districts", error);
            districtSelect.innerHTML = '<option value="">Error</option>';
        }
    }

    divisionSelect.addEventListener('change', async (e) => {
        const val = e.target.value;
        districtSelect.innerHTML = '<option value="">Select District...</option>';
        talukaSelect.innerHTML = '<option value="">Select Taluka...</option>';
        villageSelect.innerHTML = '<option value="">Select Village...</option>';
        districtSelect.disabled = true;
        talukaSelect.disabled = true;
        villageSelect.disabled = true;
        updateStartButton();

        if (val) {
            districtSelect.innerHTML = '<option value="">Loading...</option>';
            await loadDistricts(val);
        }
    });

    districtSelect.addEventListener('change', async (e) => {
        const val = e.target.value;
        talukaSelect.innerHTML = '<option value="">Select Taluka...</option>';
        villageSelect.innerHTML = '<option value="">Select Village...</option>';
        talukaSelect.disabled = true;
        villageSelect.disabled = true;
        updateStartButton();

        if (val) {
            talukaSelect.innerHTML = '<option value="">Loading...</option>';
            try {
                const talukas = await apiRequest(`/api/locations/talukas?district_value=${encodeURIComponent(val)}`);
                populateSelect(talukaSelect, talukas, 'Select Taluka...');
                talukaSelect.disabled = false;
            } catch (error) {
                talukaSelect.innerHTML = '<option value="">Error</option>';
            }
        }
    });

    talukaSelect.addEventListener('change', async (e) => {
        const dVal = districtSelect.value;
        const tVal = e.target.value;
        villageSelect.innerHTML = '<option value="">Select Village...</option>';
        villageSelect.disabled = true;
        updateStartButton();

        if (dVal && tVal) {
            villageSelect.innerHTML = '<option value="">Loading...</option>';
            try {
                const villages = await apiRequest(`/api/locations/villages?district_value=${encodeURIComponent(dVal)}&taluka_value=${encodeURIComponent(tVal)}`);
                populateSelect(villageSelect, villages, 'Select Village...');
                villageSelect.disabled = false;
            } catch (error) {
                villageSelect.innerHTML = '<option value="">Error</option>';
            }
        }
    });

    villageSelect.addEventListener('change', updateStartButton);

    function populateSelect(selectElem, items, placeholder) {
        selectElem.innerHTML = `<option value="">${placeholder}</option>`;
        items.forEach(item => {
            const opt = document.createElement('option');
            opt.value = item.value;
            opt.textContent = item.text;
            selectElem.appendChild(opt);
        });
    }

    function updateStartButton() {
        if (districtSelect.value && talukaSelect.value && villageSelect.value) {
            startBtn.disabled = false;
        } else {
            startBtn.disabled = true;
        }
    }

    // Start Download
    startBtn.addEventListener('click', async () => {
        if (!districtSelect.value || !talukaSelect.value || !villageSelect.value) return;

        startBtn.disabled = true;
        
        const payload = {
            division_text: divisionSelect.options[divisionSelect.selectedIndex]?.text || null,
            division_value: divisionSelect.value || null,
            district_text: districtSelect.options[districtSelect.selectedIndex].text,
            district_value: districtSelect.value,
            taluka_text: talukaSelect.options[talukaSelect.selectedIndex].text,
            taluka_value: talukaSelect.value,
            village_text: villageSelect.options[villageSelect.selectedIndex].text,
            village_value: villageSelect.value
        };

        try {
            const job = await apiRequest('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            // Only update currentJobId and localStorage AFTER successful POST /start
            await apiRequest(`/api/jobs/${job.id}/start`, { method: 'POST' });
            
            currentJobId = String(job.id);
            localStorage.setItem('maha_job_id', currentJobId);
            
            connectSSE(currentJobId);
            await restoreJob(currentJobId);
            
        } catch (error) {
            // Failure occurred: Do not overwrite localStorage with the invalid/failed ID.
            // Also, keep the form selection intact so the human can retry if desired.
            // Do NOT leave the button disabled permanently.
            startBtn.disabled = false;
        }
    });

    // Control Buttons
    pauseBtn.addEventListener('click', async () => {
        if (!currentJobId) return;
        pauseBtn.disabled = true;
        try {
            await apiRequest(`/api/jobs/${currentJobId}/pause`, { method: 'POST' });
            await restoreJob(currentJobId);
        } catch (error) {
            pauseBtn.disabled = false;
        }
    });

    resumeBtn.addEventListener('click', async () => {
        if (!currentJobId) return;
        resumeBtn.disabled = true;
        try {
            await apiRequest(`/api/jobs/${currentJobId}/resume`, { method: 'POST' });
            connectSSE(currentJobId);
            await restoreJob(currentJobId);
        } catch (error) {
            resumeBtn.disabled = false;
        }
    });

    retryBtn.addEventListener('click', async () => {
        if (!currentJobId) return;
        retryBtn.disabled = true;
        try {
            const res = await apiRequest(`/api/jobs/${currentJobId}/retry-failed`, { method: 'POST' });
            completionMessage.textContent = `${res.requeued_count || 'Some'} failed records requeued.`;
            completionMessage.className = 'alert alert-info mt-1';
            completionMessage.style.display = 'block';
            await restoreJob(currentJobId);
        } catch (error) {
            retryBtn.disabled = false;
        }
    });

    generateReportsBtn.addEventListener('click', async () => {
        if (!currentJobId) return;
        generateReportsBtn.disabled = true;
        generateReportsBtn.textContent = 'Generating...';
        try {
            await apiRequest(`/api/jobs/${currentJobId}/reports`, { method: 'POST' });
            completionMessage.textContent = 'Report generated successfully';
            completionMessage.className = 'alert alert-success mt-1';
            completionMessage.style.display = 'block';
            
            downloadCsvBtn.href = `/api/jobs/${currentJobId}/reports/csv`;
            downloadCsvBtn.style.display = 'inline-block';
            downloadXlsxBtn.href = `/api/jobs/${currentJobId}/reports/xlsx`;
            downloadXlsxBtn.style.display = 'inline-block';
        } catch (error) {
            // apiRequest shows notice
        } finally {
            generateReportsBtn.disabled = false;
            generateReportsBtn.textContent = 'Generate Report';
        }
    });

    // Job Management
    async function restoreJob(jobId) {
        try {
            const job = await apiRequest(`/api/jobs/${jobId}`);
            lastRestJob = job;
            updateJobUI(job);
            
            if (['CREATED', 'DISCOVERING', 'WAITING_FOR_CAPTCHA', 'RUNNING'].includes(job.status)) {
                if (!eventSource || eventSource.readyState === EventSource.CLOSED) {
                    connectSSE(jobId);
                }
            }
        } catch (error) {
            if (error.message.includes('404')) {
                localStorage.removeItem('maha_job_id');
                currentJobId = null;
            }
        }
    }

    function updateJobUI(job) {
        if (String(job.id) !== String(currentJobId)) {
            return; // Ignore stale job UI updates
        }
        
        jobSection.style.display = 'block';
        
        activeJobIdText.textContent = `Job #${job.id}`;
        activeJobLocationText.textContent = `${job.district_text || ''} -> ${job.taluka_text || ''} -> ${job.village_text || ''}`;
        
        const isTerminal = ['COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'].includes(job.status);
        
        reportControls.style.display = 'block';
        if (isTerminal) {
            downloadCsvBtn.href = `/api/jobs/${job.id}/reports/csv`;
            downloadCsvBtn.style.display = 'inline-block';
            downloadXlsxBtn.href = `/api/jobs/${job.id}/reports/xlsx`;
            downloadXlsxBtn.style.display = 'inline-block';
        }
        
        if (job.status === 'DISCOVERING') {
            jobStatusBadge.textContent = 'Discovering Survey/Gat records...';
        } else {
            jobStatusBadge.textContent = job.status.replace(/_/g, ' ');
        }
        
        // Progress text
        let total = job.total_records || 0;
        let comp = job.completed_records || 0;
        let fail = job.failed_records || 0;
        let empty = job.empty_records || 0;
        let processed = comp + fail + empty;
        
        // Total is only known once discovery has persisted the JobRecord queue.
        let totalKnown = (typeof job.total_known === 'boolean')
            ? job.total_known
            : !['CREATED', 'DISCOVERING'].includes(job.status);
        if (job.status === 'FAILED' && total === 0) totalKnown = false; // failed before discovery finished
        
        let remaining = Math.max(0, total - processed);
        
        statTotal.textContent = totalKnown ? total : '—';
        statCompleted.textContent = comp;
        statFailed.textContent = fail;
        statRemaining.textContent = totalKnown ? remaining : '—';
        
        let pct = total > 0 ? Math.floor((processed / total) * 100) : 0;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `${pct}%`;

        // ETA
        if (job.eta_seconds !== null && job.eta_seconds !== undefined) {
            jobEta.textContent = `ETA: ${job.eta_seconds}s`;
        } else if (job.eta_status) {
            let s = job.eta_status;
            if (s === 'insufficient_data') s = 'Insufficient data';
            jobEta.textContent = `ETA: ${s}`;
        } else {
            jobEta.textContent = `ETA: Calculating...`;
        }

        // Buttons
        // Start button is explicitly NOT disabled here so that an old/running job
        // doesn't prevent creating a new job if form selection changes.
        
        pauseBtn.disabled = !['WAITING_FOR_CAPTCHA', 'RUNNING'].includes(job.status);
        resumeBtn.disabled = !['PAUSED'].includes(job.status);
        
        retryBtn.disabled = !(isTerminal && fail > 0);

        // Completion Message
        completionMessage.style.display = 'none';
        if (job.status === 'COMPLETED') {
            completionMessage.textContent = 'Download completed.';
            completionMessage.className = 'alert alert-success mt-1';
            completionMessage.style.display = 'block';
        } else if (job.status === 'COMPLETED_WITH_ERRORS') {
            completionMessage.textContent = 'Download completed with errors.';
            completionMessage.className = 'alert alert-warning mt-1';
            completionMessage.style.display = 'block';
        } else if (job.status === 'FAILED') {
            completionMessage.textContent = 'Job failed.';
            completionMessage.className = 'alert alert-danger mt-1';
            completionMessage.style.display = 'block';
        }
        
        // Failed Records (refetch only when the failed count / terminal state changes)
        if (fail > 0 || isTerminal) {
            const key = `${job.id}:${fail}:${isTerminal}`;
            if (key !== lastFailedKey) {
                lastFailedKey = key;
                loadFailedRecords(job.id);
            }
        } else {
            lastFailedKey = null;
            failedRecordsSection.style.display = 'none';
        }
        
        // Current Record State (Can be supplemented by SSE)
        if (job.status === 'WAITING_FOR_CAPTCHA') {
            captchaNotice.style.display = 'block';
        } else {
            captchaNotice.style.display = 'none';
        }
    }

    async function loadFailedRecords(jobId) {
        try {
            const records = await apiRequest(`/api/jobs/${jobId}/records`);
            const failed = records.filter(r => r.status === 'FAILED');
            
            if (failed.length > 0) {
                failedRecordsSection.style.display = 'block';
                failedTableBody.innerHTML = '';
                failed.forEach(r => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td>${r.survey_identifier_original}</td>
                        <td>${r.attempt_count}</td>
                        <td>${r.last_error_code || '—'}</td>
                        <td>${r.last_error_message || '—'}</td>
                    `;
                    failedTableBody.appendChild(tr);
                });
            } else {
                failedRecordsSection.style.display = 'none';
            }
        } catch (error) {
            console.error(error);
        }
    }

    // Map the flat SSE progress payload onto the job shape used by updateJobUI.
    function applyProgressPayload(data) {
        if (String(data.job_id) !== String(currentJobId)) {
            return; // Ignore events from stale SSE connections
        }
        const job = Object.assign({}, lastRestJob || {}, {
            id: data.job_id,
            status: data.status,
            total_known: data.total_known,
            total_records: data.total === null || data.total === undefined ? 0 : data.total,
            completed_records: data.completed,
            failed_records: data.failed,
            empty_records: data.empty,
            pause_requested: data.pause_requested
        });
        updateJobUI(job);
        
        if (data.current_survey_identifier) {
            recordSection.style.display = 'block';
            currentRecordId.textContent = data.current_survey_identifier;
            currentRecordStatus.textContent = data.current_record_status || '';
        } else {
            recordSection.style.display = 'none';
        }
    }

    function connectSSE(jobId) {
        if (eventSource) {
            eventSource.close();
        }
        
        eventSource = new EventSource(`/api/jobs/${jobId}/events`);
        
        eventSource.addEventListener('progress', (e) => {
            applyProgressPayload(JSON.parse(e.data));
        });
        
        eventSource.addEventListener('human_action_required', (e) => {
            applyProgressPayload(JSON.parse(e.data));
            captchaNotice.style.display = 'block';
            jobStatusBadge.textContent = "WAITING FOR CAPTCHA";
        });

        eventSource.addEventListener('paused', (e) => {
            applyProgressPayload(JSON.parse(e.data));
            eventSource.close();
        });
        
        eventSource.addEventListener('completed', (e) => {
            applyProgressPayload(JSON.parse(e.data));
            eventSource.close();
        });
        
        eventSource.addEventListener('error', (e) => {
            console.log("SSE error/disconnect");
            if (jobStatusBadge.textContent.indexOf('Reconnecting') === -1 && 
                !['COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED', 'PAUSED'].includes(jobStatusBadge.textContent)) {
                jobStatusBadge.textContent += " [Reconnecting...]";
            }
        });
    }
});
