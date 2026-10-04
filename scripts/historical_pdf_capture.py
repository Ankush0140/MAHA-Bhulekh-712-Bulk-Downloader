import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Union
from playwright.async_api import Page


@dataclass
class PdfCaptureResult:
    created: bool
    output_path: str
    size_bytes: int
    page_count: int
    error_message: str = ""


def estimate_pdf_page_count(pdf_bytes: bytes) -> int:
    """Estimate page count from PDF binary data without external dependencies."""
    try:
        matches = re.findall(rb"/Type\s*/Page\b", pdf_bytes)
        if matches:
            return len(matches)

        count_match = re.search(rb"/Count\s+(\d+)\b", pdf_bytes)
        if count_match:
            return int(count_match.group(1))
    except Exception:
        pass
    return 1 if pdf_bytes.startswith(b"%PDF") else 0


async def inject_clean_print_styles(page: Page, target_container_selector: Optional[str] = None):
    """
    Inject clean print CSS rules to hide search form controls, mobile field, CAPTCHA,
    headers, footers, and accessibility widgets during page.pdf() execution.
    Target container (the 7/12 record) remains fully visible and unclipped.
    """
    await page.evaluate("""(containerSel) => {
        const styleId = '__clean_pdf_style__';
        let existing = document.getElementById(styleId);
        if (existing) existing.remove();

        const style = document.createElement('style');
        style.id = styleId;
        
        let targetSelector = containerSel;
        if (!targetSelector) {
            // Auto-detect container holding 'मागे जा' or 7/12 panel
            const candidate = Array.from(document.querySelectorAll('div, section, main, table')).find(el => {
                const txt = el.innerText || '';
                return (txt.includes('मागे जा') || txt.includes('सातबारा') || txt.includes('गाव नमुना')) &&
                       !el.querySelector('#ContentPlaceHolder1_ddlMainDist');
            });
            if (candidate) {
                if (!candidate.id) candidate.id = '__auto_712_container__';
                targetSelector = '#' + candidate.id;
            }
        }

        let css = `
            @media print {
                /* Hide main search form controls, mobile, CAPTCHA, headers, footers */
                #ContentPlaceHolder1_UpdatePanel1,
                #ContentPlaceHolder1_pnlForm,
                .header, .footer, header, footer, nav,
                .userway, iframe[src*="userway"],
                #ContentPlaceHolder1_txtmobile1,
                #ContentPlaceHolder1_txtcaptcha,
                #ContentPlaceHolder1_imgCaptcha,
                #ContentPlaceHolder1_btnmainsubmit {
                    display: none !important;
                }

                body, html {
                    background: #ffffff !important;
                    color: #000000 !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    width: 100% !important;
                }

                @page {
                    size: A4 portrait;
                    margin: 10mm;
                }
            }
        `;

        if (targetSelector) {
            css += `
                @media print {
                    ${targetSelector}, ${targetSelector} * {
                        visibility: visible !important;
                    }
                }
            `;
        }

        style.innerHTML = css;
        document.head.appendChild(style);
    }""", target_container_selector)


async def remove_clean_print_styles(page: Page):
    """Remove injected clean print CSS to restore normal browser UI state."""
    try:
        await page.evaluate("""() => {
            const el = document.getElementById('__clean_pdf_style__');
            if (el) el.remove();
        }""")
    except Exception:
        pass


async def save_rendered_record_as_pdf(
    page: Page,
    output_path: Union[str, Path],
    target_container_selector: Optional[str] = None,
    print_background: bool = True,
    prefer_css_page_size: bool = True
) -> PdfCaptureResult:
    """
    Capture the currently rendered 7/12 record cleanly using DOM-based print CSS injection.
    Hides surrounding search form, mobile field, CAPTCHA, and site clutter during printing,
    restoring normal page state immediately afterwards.
    """
    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Inject temporary print CSS rules
        await inject_clean_print_styles(page, target_container_selector)

        # 2. Execute Playwright print-to-PDF
        await page.pdf(
            path=str(target_path),
            print_background=print_background,
            prefer_css_page_size=prefer_css_page_size
        )
    except Exception as err:
        return PdfCaptureResult(
            created=False,
            output_path=str(target_path),
            size_bytes=0,
            page_count=0,
            error_message=f"Playwright page.pdf() exception: {err}"
        )
    finally:
        # 3. Immediately restore page CSS
        await remove_clean_print_styles(page)

    # 4. Validate output PDF
    if not target_path.exists():
        return PdfCaptureResult(
            created=False,
            output_path=str(target_path),
            size_bytes=0,
            page_count=0,
            error_message="PDF file was not created on disk."
        )

    size = target_path.stat().st_size
    if size == 0:
        return PdfCaptureResult(
            created=False,
            output_path=str(target_path),
            size_bytes=0,
            page_count=0,
            error_message="PDF file created on disk is empty (0 bytes)."
        )

    with open(target_path, "rb") as f:
        header = f.read(1024)
        if not header.startswith(b"%PDF"):
            return PdfCaptureResult(
                created=False,
                output_path=str(target_path),
                size_bytes=size,
                page_count=0,
                error_message="File header does not begin with valid %PDF signature."
            )

        f.seek(0)
        full_bytes = f.read()
        page_count = estimate_pdf_page_count(full_bytes)

    return PdfCaptureResult(
        created=True,
        output_path=str(target_path),
        size_bytes=size,
        page_count=page_count,
        error_message=""
    )
