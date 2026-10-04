from dataclasses import dataclass
from typing import Optional, Tuple
from app.models.location import LocationSelection

class LocationReadError(Exception):
    pass

class SurveyReadError(Exception):
    pass

JS_GET_LOCATION = """
() => {
    function getSel(id) {
        const el = document.querySelector(id);
        if (!el || el.selectedIndex <= 0) return null;
        return {
            text: el.options[el.selectedIndex].text.trim(),
            value: el.options[el.selectedIndex].value.trim()
        };
    }
    
    function getSurvey(id) {
        const el = document.querySelector(id);
        if (!el || el.selectedIndex < 0) return null;
        return {
            text: el.options[el.selectedIndex].text.trim(),
            value: el.options[el.selectedIndex].value.trim()
        };
    }

    const dist = getSel('#ContentPlaceHolder1_ddlMainDist');
    const tal = getSel('#ContentPlaceHolder1_ddlTalForAll');
    const vill = getSel('#ContentPlaceHolder1_ddlVillForAll');
    const survey = getSurvey('#ContentPlaceHolder1_ddlsurveyno');
    
    return {
        district: dist,
        taluka: tal,
        village: vill,
        survey: survey
    };
}
"""

async def read_location_selection(page) -> Tuple[LocationSelection, str]:
    """
    Reads the actual selected location and survey from the Bhulekh DOM.
    Returns (LocationSelection, survey_text).
    Raises error if any required field is missing/placeholder.
    """
    result = await page.evaluate(JS_GET_LOCATION)
    
    if not result.get("district"):
        raise LocationReadError("LOCATION_SELECTION_UNAVAILABLE: District not selected or element not found")
    if not result.get("taluka"):
        raise LocationReadError("LOCATION_SELECTION_UNAVAILABLE: Taluka not selected or element not found")
    if not result.get("village"):
        raise LocationReadError("LOCATION_SELECTION_UNAVAILABLE: Village not selected or element not found")
        
    loc = LocationSelection(
        district_text=result["district"]["text"],
        district_value=result["district"]["value"],
        taluka_text=result["taluka"]["text"],
        taluka_value=result["taluka"]["value"],
        village_text=result["village"]["text"],
        village_value=result["village"]["value"],
        division=None
    )
    
    if not result.get("survey"):
        raise SurveyReadError("SURVEY_IDENTIFIER_UNAVAILABLE: Survey/Gat not selected or element not found")
        
    survey_text = result["survey"]["text"]
    
    return loc, survey_text
