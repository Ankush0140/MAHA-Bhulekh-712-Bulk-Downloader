import re
from pathlib import Path
from typing import Union

INVALID_WINDOWS_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename_component(component: str) -> str:
    """
    Sanitize a filename component for Windows OS compatibility.
    Replaces Windows illegal characters (< > : " / \\ | ? *) with hyphens.
    Preserves Unicode (Devanagari) and Latin letters while preventing path traversal.
    """
    if not component:
        return ""

    # Replace path separators and invalid Windows characters with hyphens
    sanitized = INVALID_WINDOWS_CHARS_RE.sub("-", component)

    # Collapse multiple consecutive hyphens or spaces
    sanitized = re.sub(r"-+", "-", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)

    # Strip leading/trailing spaces, dots, and hyphens to avoid Windows naming bugs
    sanitized = sanitized.strip(" .-_")

    if not sanitized or sanitized in [".", ".."]:
        return ""

    return sanitized


import json

def build_output_filepath(
    location: "LocationSelection",
    survey_number: str,
    base_output_dir: Union[str, Path],
    extension: str = "pdf"
) -> Path:
    """
    Build a safe, organized output FilePath for a land record using actual runtime selection.
    Structure: base_output_dir / [Division /] District / Taluka / Village / District_Taluka_Village_Survey.pdf
    Avoids duplicate folder names when Division and District are identical (e.g. Division/District -> output/<District>/<Taluka>/<Village>).
    Implements collision protection using a metadata sidecar file.
    """
    base_dir = Path(base_output_dir).resolve()

    division = location.division_text if location.division_text else ""
    safe_division = sanitize_filename_component(division)
    safe_district = sanitize_filename_component(location.district_text)
    safe_taluka = sanitize_filename_component(location.taluka_text)
    safe_village = sanitize_filename_component(location.village_text)
    safe_survey = sanitize_filename_component(survey_number)

    if not safe_district:
        raise ValueError("LOCATION_SELECTION_UNAVAILABLE: District name cannot be empty")
    if not safe_taluka:
        raise ValueError("LOCATION_SELECTION_UNAVAILABLE: Taluka name cannot be empty")
    if not safe_village:
        raise ValueError("LOCATION_SELECTION_UNAVAILABLE: Village name cannot be empty")
    if not safe_survey:
        raise ValueError("SURVEY_IDENTIFIER_UNAVAILABLE: Survey identifier cannot be empty")

    folder_path = base_dir / safe_district / safe_taluka / safe_village

    folder_path.mkdir(parents=True, exist_ok=True)

    ext = extension.lstrip(".")
    filename = f"{safe_district}_{safe_taluka}_{safe_village}_{safe_survey}.{ext}"
    output_path = folder_path / filename

    # Collision protection using metadata sidecar
    meta_path = output_path.with_suffix(".meta.json")
    if output_path.exists():
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("original_survey") != survey_number:
                    raise FileExistsError(f"Collision detected for {survey_number}: {filename} belongs to {meta.get('original_survey')}")
            except (json.JSONDecodeError, OSError):
                # If meta is unreadable, play it safe and assume collision
                raise FileExistsError(f"Collision detected for {survey_number}: {filename} exists but metadata is corrupted.")
        else:
            raise FileExistsError(f"Collision detected for {survey_number}: {filename} exists without metadata.")
    
    # Save the original survey mapping immediately for future collision checks
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"original_survey": survey_number}, f, ensure_ascii=False)

    return output_path
