from fastapi import APIRouter, Query, HTTPException, status
from typing import List, Optional
from app.schemas import LocationItem
from app.services.location_service import (
    get_divisions,
    get_districts,
    get_talukas,
    get_villages
)

router = APIRouter(prefix="/api/locations", tags=["locations"])

@router.get("/divisions", response_model=List[LocationItem])
async def read_divisions():
    """
    Returns application-level verified administrative divisions.
    """
    try:
        return await get_divisions()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/districts", response_model=List[LocationItem])
async def read_districts(division_value: Optional[str] = Query(None)):
    """
    Returns districts, optionally filtered by application-level division.
    """
    try:
        return await get_districts(division_value)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/talukas", response_model=List[LocationItem])
async def read_talukas(district_value: str = Query(..., description="The value of the selected district")):
    try:
        return await get_talukas(district_value)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

@router.get("/villages", response_model=List[LocationItem])
async def read_villages(
    district_value: str = Query(...),
    taluka_value: str = Query(...)
):
    try:
        return await get_villages(district_value, taluka_value)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
