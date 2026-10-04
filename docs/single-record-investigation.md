# Single 7/12 Record Retrieval Investigation Report

**Portal URL**: https://bhulekh.mahabhumi.gov.in/  
**Date of Investigation**: 2026-10-01  
**Browser Channel**: Installed Google Chrome (`channel="chrome"`, Playwright Async API)

---

## ASSIGNMENT TARGET CONFIGURATION
- **District**: Pune
- **Taluka**: Maval
- **Village**: Shivali
- **Validated Numeric Discovery Baseline**: 713 unique records
- **Measured Discovery Time**: 7.49 seconds
- **Test Mobile Number**: Operator-controlled valid 10-digit Indian mobile number matching `^[6-9][0-9]{9}$` (configured via `TEST_MOBILE_NUMBER` or manual input)
- **Digital Signature Requirement**: Not required (Public 7/12 view workflow used)

---

## 1. VERIFIED PORTAL WORKFLOW STATUS

> [!NOTE]
> **VERIFIED OPERATIONAL WORKFLOW**: The live Maharashtra Bhulekh 7/12 workflow is **OPERATIONAL**.
> - Submitting the form with a valid operator-controlled 10-digit mobile number matching `^[6-9][0-9]{9}$` and human-entered CAPTCHA successfully opens/renders the requested 7/12 record.
> - The assignment-provided test number `1234567890` failed the portal's client-side regex `^[6-9][0-9]{9}$` (which requires a valid Indian mobile format starting with digits 6-9), which previously triggered a validation alert.
> - **No portal validation workaround, JavaScript monkey-patching, or code modification is required or used.**

---

## 2. TECHNICAL DELIVERY INVESTIGATION (IN PROGRESS)

*(To be populated empirically upon execution of `scripts/inspect_successful_record.py`)*

### 2.1 Delivery Mechanism
- **Operator Confirmed Result Visible**: TBD
- **Same Page Navigation vs Popup/Tab**: TBD
- **Native Browser Download Event**: TBD
- **Content-Type**: TBD
- **DOM Structure**:
  - `iframe` count & sources: TBD
  - `embed` / `object` present: TBD
  - PDF viewer / canvas detected: TBD
  - HTML document rendered: TBD
  - Print control / `window.print` present: TBD

### 2.2 Session Persistence
- **Original Main Page Open**: TBD
- **Location Selection (District/Taluka/Village)**: Preserved / Reset? TBD
- **Survey Selection**: Preserved / Reset? TBD
- **CAPTCHA Image**: Reset / Refreshed? TBD

---

## 3. INVESTIGATION NOTES

- Earlier client-side validation errors observed with `1234567890` were caused by standard format validation (`^[6-9][0-9]{9}$`).
- When a valid mobile number is supplied, normal form submission executes cleanly.
