# MAHA Bhulekh 7/12 Bulk Downloader

A local web application for Maharashtra Bhulekh 7/12 land record discovery and bulk downloading.

## Setup Instructions (Windows)

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

4. Run the application:
   ```cmd
   python run.py
   ```
   or using uvicorn directly:
   ```cmd
   uvicorn app.main:app --reload
   ```

5. Access the web interface at:
   `http://127.0.0.1:8000`

6. Run unit tests:
   ```cmd
   pytest
   ```

## Limitations

- The verified Maharashtra hierarchy contains 36 administrative districts. The inspected Bhulekh District dropdown exposed 35 options; Mumbai City was not observed as a separate option and no portal value is fabricated for it.
- Division is an application-side administrative grouping based on verified Government of Maharashtra revenue-division sources. District options and their portal values come from Bhulekh and are classified using explicit verified portal-label mappings.
