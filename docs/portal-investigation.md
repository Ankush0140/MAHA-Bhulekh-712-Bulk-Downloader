# MAHA Bhulekh Portal Investigation & Discovery Strategy Report

**Portal URL**: https://bhulekh.mahabhumi.gov.in/  
**Date of Investigation**: 2026-10-01  
**Browser Channel**: Installed Google Chrome (`channel="chrome"`, Playwright Async API)

---

## 1. VERIFIED OBSERVATIONS

### 1.1 Portal Overview & Form Controls (ASP.NET WebForms)
- **Portal Title**: Mahabhulekh v2.0
- **District Selector**: `#ContentPlaceHolder1_ddlMainDist`
- **Taluka Selector**: `#ContentPlaceHolder1_ddlTalForAll`
- **Village Selector**: `#ContentPlaceHolder1_ddlVillForAll`
- **Search Type Selector**: `#ContentPlaceHolder1_ddlSelectSearchType`
  - Value `2`: Numeric Survey Number mode (सर्वे नंबर)
  - Value `8`: Akshar Survey Number mode (अक्षरी सर्वे नंबर)
- **Part-1 Search Input**: `#ContentPlaceHolder1_txtcsno`
- **Search Button**: `#ContentPlaceHolder1_btnsearchfind`
- **Survey Number Result Dropdown**: `#ContentPlaceHolder1_ddlsurveyno`

### 1.2 Survey Search & Result Dropdown Behavior (Numeric Mode)
- **Prefix-Based Search**: Entering numeric digits `1` through `9` triggers server-side filtering populating `#ContentPlaceHolder1_ddlsurveyno`.
- **Empirical Prefix Baseline (Test Village)**:
  - Prefix `1`: 280 records
  - Prefix `2`: 165 records
  - Prefix `3`: 176 records
  - Prefix `4`: 111 records
  - Prefix `5`: 111 records
  - Prefix `6`: 52 records
  - Prefix `7`: 11 records
  - Prefix `8`: 11 records
  - Prefix `9`: 11 records
  - **Total Discovered Options**: 928 records (0 duplicates between prefixes 1-9).
- **Subdivision / Hissa Representation**: Exact option texts and values expose all subdivisions (e.g., `115/1/A`, `115/10/B`, `10/1/अ`). Exact option strings are preserved without numeric truncation or character stripping.

### 1.3 Akshar Survey Number Mode Limitation
- **Verified Behavior**: Selecting search type value `8` (अक्षरी सर्वे नंबर) hides the `#ContentPlaceHolder1_txtcsno` input field while keeping the Search button `#ContentPlaceHolder1_btnsearchfind` visible.
- **Test Result**: Clicking Search once without a text input resulted in an HTTP 200 POST response (elapsed time ~2.93 seconds), but zero survey options were returned in `#ContentPlaceHolder1_ddlsurveyno`.
- **Limitation Documented**: Akshar survey mode does not auto-populate options on empty search. Production discovery currently supports Numeric Survey discovery (`value="2"`).

### 1.4 CAPTCHA Boundary
- **Empirical Boundary**: District, Taluka, and Village selection as well as numeric survey discovery occur entirely **BEFORE** CAPTCHA input.
- CAPTCHA is required only on the main form prior to submitting individual 7/12 land record requests.

---

## 2. PRODUCTION DISCOVERY ARCHITECTURE

### 2.1 Supported Capabilities
- **SUPPORTED**: Numeric Survey/Gat Discovery via prefix traversal (`1` through `9`).
- **CURRENT LIMITATION**: Akshar Survey Number Discovery (Not yet supported; zero options returned on empty search).
- **CAPTCHA Requirement**: Not required during discovery phase.

### 2.2 Discovery Pipeline
1. Ensure Search Type is set to Numeric mode (`value="2"`).
2. Sequentially fill Part-1 input for prefixes `1` through `9`.
3. Synchronize via ASP.NET WebForms postback response (`expect_response` on POST request).
4. Extract options, remove placeholder items (`--निवडा--`, value `0`/`""`), and deduplicate using exact `(option_value, display_text)` identity.
