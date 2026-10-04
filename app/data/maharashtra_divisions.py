"""
Verified administrative hierarchy from official Government of Maharashtra / Divisional Commissioner sources.

Division is an APPLICATION-SIDE administrative grouping.
Bhulekh provides District -> Taluka -> Village.
"""
from typing import List, Dict, Optional

class Division:
    def __init__(self, value: str, text: str, districts: List[str]):
        self.value = value
        self.text = text
        self.districts = districts

DIVISIONS = [
    Division(
        value="pune",
        text="Pune Division",
        districts=["Pune", "Satara", "Sangli", "Solapur", "Kolhapur"]
    ),
    Division(
        value="nashik",
        text="Nashik Division",
        districts=["Nashik", "Dhule", "Nandurbar", "Ahilyanagar", "Jalgaon"]
    ),
    Division(
        value="chhatrapati-sambhajinagar",
        text="Chhatrapati Sambhajinagar Division",
        districts=["Chhatrapati Sambhajinagar", "Beed", "Jalna", "Parbhani", "Latur", "Hingoli", "Nanded", "Dharashiv"]
    ),
    Division(
        value="amravati",
        text="Amravati Division",
        districts=["Amravati", "Akola", "Buldhana", "Washim", "Yavatmal"]
    ),
    Division(
        value="nagpur",
        text="Nagpur Division",
        districts=["Nagpur", "Wardha", "Bhandara", "Gondia", "Chandrapur", "Gadchiroli"]
    ),
    Division(
        value="konkan",
        text="Konkan Division",
        districts=["Mumbai City", "Mumbai Suburban", "Thane", "Palghar", "Raigad", "Ratnagiri", "Sindhudurg"]
    )
]

# Provide known aliases for actual Bhulekh district labels that might appear differently
# e.g. "Ahmednagar" -> "Ahilyanagar" if Bhulekh hasn't updated yet.
# Keys should be lowercase to allow case-insensitive exact match.
KNOWN_ALIASES = {
    "ahmednagar": "Ahilyanagar",
    "aurangabad": "Chhatrapati Sambhajinagar",
    "osmanabad": "Dharashiv",
    "अकोला": "Akola",
    "अमरावती": "Amravati",
    "बुलडाणा": "Buldhana",
    "यवतमाळ": "Yavatmal",
    "वाशिम": "Washim",
    "धाराशिव": "Dharashiv",
    "छत्रपती संभाजीनगर": "Chhatrapati Sambhajinagar",
    "जालना": "Jalna",
    "नांदेड": "Nanded",
    "परभणी": "Parbhani",
    "बीड": "Beed",
    "लातूर": "Latur",
    "हिंगोली": "Hingoli",
    "ठाणे": "Thane",
    "पालघर": "Palghar",
    "मंबई उपनगर": "Mumbai Suburban",
    "रत्नागिरी": "Ratnagiri",
    "रायगड": "Raigad",
    "सिंधुदुर्ग": "Sindhudurg",
    "गडचिरोली": "Gadchiroli",
    "गोंदिया": "Gondia",
    "चंद्रपूर": "Chandrapur",
    "नागपूर": "Nagpur",
    "भंडारा": "Bhandara",
    "वर्धा": "Wardha",
    "अहिल्यानगर": "Ahilyanagar",
    "जळगाव": "Jalgaon",
    "धुळे": "Dhule",
    "नंदुरबार": "Nandurbar",
    "नाशिक": "Nashik",
    "कोल्हापूर": "Kolhapur",
    "पुणे": "Pune",
    "सांगली": "Sangli",
    "सातारा": "Satara",
    "सोलापूर": "Solapur",
}

def get_divisions_metadata() -> List[Dict[str, str]]:
    """Returns application-side division values and display texts."""
    return [{"text": d.text, "value": d.value} for d in DIVISIONS]

def get_division_for_district(portal_district_label: str) -> Optional[str]:
    """
    Returns the division.value (e.g., 'pune') for a given portal district label.
    Performs exact match or verified alias match. Does NOT substring match.
    """
    cleaned_label = portal_district_label.strip()
    
    # Check exact match
    for d in DIVISIONS:
        for dist in d.districts:
            if dist.lower() == cleaned_label.lower():
                return d.value
                
    # Check aliases
    alias = KNOWN_ALIASES.get(cleaned_label.lower())
    if alias:
        for d in DIVISIONS:
            for dist in d.districts:
                if dist.lower() == alias.lower():
                    return d.value
                    
    return None
