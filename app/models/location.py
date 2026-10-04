from dataclasses import dataclass
from typing import Optional

@dataclass
class LocationSelection:
    # Portal metadata
    district_text: str
    district_value: str
    taluka_text: str
    taluka_value: str
    village_text: str
    village_value: str
    
    # Division is application-side administrative metadata, NOT a portal value
    division_text: Optional[str] = None
    division_value: Optional[str] = None
