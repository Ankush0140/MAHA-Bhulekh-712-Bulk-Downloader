# Demo Video Script & Walkthrough

This guide provides a step-by-step script for recording a 3–5 minute demonstration of the MAHA Bhulekh 7/12 Bulk Downloader.

## Preparation
1. Ensure the application is running (`python run.py`).
2. Have your screen recorder ready.
3. Ensure no personal or sensitive tabs are visible.

## Walkthrough Steps

### 1. Location Selection & Job Initiation
- **Action**: Open the web interface (`http://127.0.0.1:8000`). Select a Division, District, Taluka, and Village.
- **Narration**: *"Welcome. First, we select our target location from the UI."*
- **Action**: Click the **Start Download** button.
- **Narration**: *"I will now start the bulk download job. The application securely queries the Bhulekh portal to discover all available survey numbers for this village, queues them up, and begins processing."*

### 3. Human CAPTCHA Workflow
- **Action**: Wait for the application to pause and bring the Playwright browser window to the front.
- **Narration**: *"The application has reached the CAPTCHA stage. As per our strict compliance policy, the automation pauses here. I will now manually enter the mobile number and solve the CAPTCHA."*
- **Action**: Manually enter the mobile number, solve the CAPTCHA, and click the Verify button in the portal.
- **Narration**: *"Once verified, the portal displays the 7/12 record. The application detects this successful result, automatically captures the PDF, and seamlessly moves on to the next record."*

### 4. Live Counters & Job Control (Pause/Resume)
- **Action**: Show the UI updating the "Completed" counter. Then, click the **Pause** button.
- **Narration**: *"Back in the UI, you can see the live counters updating. We can safely Pause the job at any time. Let's pause it now."*
- **Action**: Wait for the status to show Paused, then click **Resume**.
- **Narration**: *"The job is paused without losing state. I will now Resume the job to continue the queue."*

### 5. Error Handling (If Applicable)
- **Action**: If a timeout or error occurs, point out the "Failed" counter and the Error Category in the UI.
- **Narration**: *"If the Bhulekh portal times out, the application uses a robust retry queue. Technical timeouts are logged cleanly and are not counted as CAPTCHA failures."*

### 6. Output Review
- **Action**: In the UI, click **Generate Report**. Wait for it to say "Report generated successfully", then click **Download CSV** and **Download Excel**.
- **Narration**: *"Even while paused or partially complete, we can manually generate and download live reports directly from the UI."*
- **Action**: Open your file explorer and navigate to the `output/` directory (e.g., `output/District/Taluka/Village/`).
- **Narration**: *"Here is the beautifully structured folder hierarchy containing our downloaded 7/12 PDFs alongside the generated reports."*
- **Action**: Open the generated `District_Taluka_Village_summary.csv` or `.xlsx` file.
- **Narration**: *"Notice how the report cleanly tracks and separates the 'Automated Processing Seconds' from the 'Human Verification Seconds' for precise performance benchmarking."*

## End of Demo
- **Action**: Stop recording.
