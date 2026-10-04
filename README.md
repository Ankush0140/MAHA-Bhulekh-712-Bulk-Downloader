# MAHA Bhulekh 7/12 Bulk Downloader

## Project Overview
A local web application for Maharashtra Bhulekh 7/12 land record discovery and bulk downloading. It automates the discovery of survey numbers and the downloading of digitally signed (if available) or standard 7/12 land records.

## Features
- **Automated Survey Discovery**: Automatically finds available survey/gat numbers for a selected village.
- **Bulk Downloading**: Queues and downloads PDFs systematically.
- **Human-in-the-Loop CAPTCHA**: Securely hands over control to the user when CAPTCHA or mobile verification is required by the portal.
- **Resilience**: Robust retry queues, error handling, and session recovery.
- **Comprehensive Reporting**: Generates CSV and Excel summary reports tracking processing and wait times.

## Architecture
The application uses a modern async stack:
- **FastAPI / Uvicorn**: Backend server and API.
- **Playwright (Chromium)**: Headless/headed browser automation for precise DOM interaction.
- **SQLite**: Local persistence for job state, retry queues, and statistics.
- **TailwindCSS / Vanilla JS**: Lightweight, responsive frontend interface.

## Requirements
- Windows OS
- Python 3.11+
- Chrome/Chromium browser

## Installation
1. Create and activate a Python 3.11 virtual environment:
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   ```
3. Install Playwright browser binaries:
   ```cmd
   playwright install chromium
   ```

## Running the Application
Always run the application using the designated entry point:
```cmd
python run.py
```
*(IMPORTANT: Do not use `uvicorn --reload` as this project's Windows/Playwright integration is specifically orchestrated through `run.py`)*

Access the web interface at: `http://127.0.0.1:8000`

## Usage Workflow
1. **Location Selection**: Select Division, District, Taluka, and Village.
2. **Discovery**: The app automatically extracts all available survey numbers.
3. **Queue & Download**: Review discovered numbers and click Start Download.
4. **Processing**: The application prepares each record and prompts for human intervention when necessary.

## Human CAPTCHA Workflow
The application does not crack, bypass, OCR, replay, or automate CAPTCHA. CAPTCHA is completed manually on the official Maharashtra Bhulekh website whenever the portal requests it.

When the portal requests verification:
1. The automation pauses.
2. The browser window is brought to the front.
3. The operator manually enters the mobile number and solves the CAPTCHA.
4. Once the operator submits and the official 7/12 record is displayed, the automation detects the successful result, captures the PDF, and resumes bulk processing.

## Pause / Resume / Retry
- **Pause/Resume**: Long-running jobs can be safely paused from the UI and resumed later without losing progress.
- **Retry**: Failed records are safely queued and can be retried automatically or manually after a job completes.

## Output Structure
Successfully downloaded PDFs and generated reports are stored locally:
```
output/
└── District/
    └── Taluka/
        └── Village/
            ├── District_Taluka_Village_SurveyNo.pdf
            ├── ...
            ├── District_Taluka_Village_summary.csv
            └── District_Taluka_Village_summary.xlsx
```

## CSV / Excel Reporting
At the end of a job, the system generates comprehensive `report.csv` and `report.xlsx` files. The report includes:
- **Survey/Gat/Hissa**: The target identifier.
- **Status**: COMPLETED, FAILED, etc.
- **Attempts**: Number of automation attempts.
- **Output File**: Relative path to the downloaded PDF.
- **Error Category / Message**: Context on any failures.
- **Automated Processing Seconds**: Pure automation time.
- **Human Verification Seconds**: Time spent strictly waiting for the operator to solve CAPTCHA.
- **Location Hierarchy**: Division, District, Taluka, Village.

## Reliability / Retry Strategy
The system features bounded retry mechanisms for network timeouts, ASP.NET postback failures, and session drops. A technical retry (e.g., waiting for Bhulekh servers to respond) is managed strictly by the automation and is NOT counted as a CAPTCHA attempt. The application safely resets state and falls back to human verification when navigation state becomes uncertain.

## Performance
*Note: Unmeasured values are marked as [Pending final benchmark].*

| Metric | Value |
|--------|-------|
| Sample Village | [Pending final benchmark] |
| Records Tested | [Pending final benchmark] |
| Completed | [Pending final benchmark] |
| Failed | [Pending final benchmark] |
| Average Automated Time/Record | [Pending final benchmark] |
| Total Automated Processing Time | [Pending final benchmark] |
| Human CAPTCHA Wait Time | [Pending final benchmark] |
| Network/Timeout Time | [Pending final benchmark] |
| Total Elapsed Test Time | [Pending final benchmark] |

*(Automated processing time is rigorously measured separately from human CAPTCHA waiting time).*

## Official API & Bulk-Access Research
For information regarding the research into official APIs and bulk-access mechanisms, please read our [API and Bulk-Access Document](docs/api-and-bulk-access.md).

## Privacy, Compliance & Legal
- **Educational/Assignment Purpose**: This tool is developed strictly as a technical assignment and educational proof-of-concept.
- **Official Portal Source**: The official Bhulekh portal remains the sole source of truth. Please verify whether the portal provides digitally signed 7/12s or standard online views for your selected region.
- **Human-in-the-Loop**: The CAPTCHA verification is strictly manual. There is no OCR, bypassing, or replaying of tokens.
- **No Persistence of PII**: Mobile numbers and CAPTCHA values entered by the operator during verification are NOT intentionally captured, logged, or persisted by this application.
- **Controlled Access**: The system enforces controlled request rates and concurrency to respect the portal's stability.
- **Compliance Responsibility**: Users of this software are entirely responsible for complying with the official Maharashtra Bhulekh Terms of Service, applicable laws, and data privacy regulations. Downloaded land-record information must be handled appropriately.
- **No Legal Guarantees**: The developers provide no legal guarantees or warranties regarding the use of this software.

## Known Limitations
- The verified Maharashtra hierarchy contains 36 administrative districts. The inspected Bhulekh District dropdown exposed 35 options; Mumbai City was not observed as a separate option and no portal value is fabricated for it.
- Division is an application-side administrative grouping based on verified Government of Maharashtra revenue-division sources. District options and their portal values come from Bhulekh and are classified using explicit verified portal-label mappings.
- Testing has established that verification and session behavior can reset between records or after navigation/session/network delays, so the application does not guarantee one-CAPTCHA bulk operation. If the official portal preserves verification naturally during a session, the application may continue using that same browser session, but it does not manipulate the verification mechanism.

## Testing
Run unit and integration tests using:
```cmd
pytest
```

## Demo Instructions
See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for a step-by-step guide on how to demonstrate the functionality of this application.
