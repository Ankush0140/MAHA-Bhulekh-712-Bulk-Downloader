import pytest
from app.data.maharashtra_divisions import (
    DIVISIONS,
    get_divisions_metadata,
    get_division_for_district
)
from app.services.location_service import get_districts
from app.schemas import LocationItem

def test_division_mapping_counts():
    assert len(DIVISIONS) == 6
    
    all_districts = []
    for d in DIVISIONS:
        all_districts.extend(d.districts)
        
    assert len(all_districts) == 36
    assert len(set(all_districts)) == 36  # no duplicates

def test_specific_district_mappings():
    # Pune -> Pune
    assert get_division_for_district("Pune") == "pune"
    # Satara -> Pune
    assert get_division_for_district("Satara") == "pune"
    # Dhule -> Nashik
    assert get_division_for_district("Dhule") == "nashik"
    # Ahilyanagar -> Nashik
    assert get_division_for_district("Ahilyanagar") == "nashik"
    # Chhatrapati Sambhajinagar -> Chhatrapati Sambhajinagar
    assert get_division_for_district("Chhatrapati Sambhajinagar") == "chhatrapati-sambhajinagar"
    # Dharashiv -> Chhatrapati Sambhajinagar
    assert get_division_for_district("Dharashiv") == "chhatrapati-sambhajinagar"
    # Amravati -> Amravati
    assert get_division_for_district("Amravati") == "amravati"
    # Yavatmal -> Amravati
    assert get_division_for_district("Yavatmal") == "amravati"
    # Nagpur -> Nagpur
    assert get_division_for_district("Nagpur") == "nagpur"
    # Gadchiroli -> Nagpur
    assert get_division_for_district("Gadchiroli") == "nagpur"
    # Thane -> Konkan
    assert get_division_for_district("Thane") == "konkan"
    # Sindhudurg -> Konkan
    assert get_division_for_district("Sindhudurg") == "konkan"
    
def test_alias_mapping():
    assert get_division_for_district("Ahmednagar") == "nashik"
    assert get_division_for_district("Aurangabad") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("Osmanabad") == "chhatrapati-sambhajinagar"

def _patch_portal_districts(monkeypatch, items):
    import app.services.location_service as ls

    async def fake_fetch():
        return list(items)

    monkeypatch.setattr(ls, "_fetch_portal_districts", fake_fetch)


@pytest.mark.asyncio
async def test_portal_value_preservation(monkeypatch):
    # Inject a portal response containing an exact label with an arbitrary portal value
    _patch_portal_districts(monkeypatch, [
        LocationItem(text="Pune", value="test-pune"),
        LocationItem(text="Satara", value="test-satara"),
        LocationItem(text="Dhule", value="test-dhule"),
    ])

    filtered_pune = await get_districts("pune")
    assert [d.value for d in filtered_pune] == ["test-pune", "test-satara"]

    pune_dist = next(d for d in filtered_pune if d.text == "Pune")
    assert pune_dist.value == "test-pune"

@pytest.mark.asyncio
async def test_unknown_district(monkeypatch):
    _patch_portal_districts(monkeypatch, [
        LocationItem(text="पुणे", value="25"),
        LocationItem(text="UnknownDistrict", value="test-unknown"),
    ])
    # It shouldn't appear in ANY valid division.
    for d in DIVISIONS:
        filtered = await get_districts(d.value)
        assert not any(x.text == "UnknownDistrict" for x in filtered)

    # It DOES appear if no division is filtered
    all_dists = await get_districts()
    assert any(x.text == "UnknownDistrict" for x in all_dists)

@pytest.mark.asyncio
async def test_production_district_list_has_no_test_values():
    all_dists = await get_districts()
    assert len(all_dists) == 35
    assert all(not d.text.isascii() for d in all_dists)
    assert all(d.value.isdigit() and int(d.value) <= 36 for d in all_dists)

@pytest.mark.asyncio
async def test_live_distribution():
    amravati = await get_districts("amravati")
    chhatrapati = await get_districts("chhatrapati-sambhajinagar")
    konkan = await get_districts("konkan")
    nagpur = await get_districts("nagpur")
    nashik = await get_districts("nashik")
    pune = await get_districts("pune")

    assert len(amravati) == 5
    assert len(chhatrapati) == 8
    assert len(konkan) == 6
    assert len(nagpur) == 6
    assert len(nashik) == 5
    assert len(pune) == 5

    total = len(amravati) + len(chhatrapati) + len(konkan) + len(nagpur) + len(nashik) + len(pune)
    assert total == 35

def test_marathi_alias_mapping():
    assert get_division_for_district("अकोला") == "amravati"
    assert get_division_for_district("अमरावती") == "amravati"
    assert get_division_for_district("बुलडाणा") == "amravati"
    assert get_division_for_district("यवतमाळ") == "amravati"
    assert get_division_for_district("वाशिम") == "amravati"
    
    assert get_division_for_district("धाराशिव") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("छत्रपती संभाजीनगर") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("जालना") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("नांदेड") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("परभणी") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("बीड") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("लातूर") == "chhatrapati-sambhajinagar"
    assert get_division_for_district("हिंगोली") == "chhatrapati-sambhajinagar"
    
    assert get_division_for_district("ठाणे") == "konkan"
    assert get_division_for_district("पालघर") == "konkan"
    assert get_division_for_district("मंबई उपनगर") == "konkan"
    assert get_division_for_district("रत्नागिरी") == "konkan"
    assert get_division_for_district("रायगड") == "konkan"
    assert get_division_for_district("सिंधुदुर्ग") == "konkan"
    
    assert get_division_for_district("गडचिरोली") == "nagpur"
    assert get_division_for_district("गोंदिया") == "nagpur"
    assert get_division_for_district("चंद्रपूर") == "nagpur"
    assert get_division_for_district("नागपूर") == "nagpur"
    assert get_division_for_district("भंडारा") == "nagpur"
    assert get_division_for_district("वर्धा") == "nagpur"
    
    assert get_division_for_district("अहिल्यानगर") == "nashik"
    assert get_division_for_district("जळगाव") == "nashik"
    assert get_division_for_district("धुळे") == "nashik"
    assert get_division_for_district("नंदुरबार") == "nashik"
    assert get_division_for_district("नाशिक") == "nashik"
    
    assert get_division_for_district("कोल्हापूर") == "pune"
    assert get_division_for_district("पुणे") == "pune"
    assert get_division_for_district("सांगली") == "pune"
    assert get_division_for_district("सातारा") == "pune"
    assert get_division_for_district("सोलापूर") == "pune"

@pytest.mark.asyncio
async def test_assignment_target():
    # Prove exact portal string is matched to Pune Division, and the portal option is returned intact
    pune_div = await get_districts("pune")
    matched = next((d for d in pune_div if d.text == "पुणे"), None)
    assert matched is not None
    assert matched.value == "25"
    assert matched.text == "पुणे"

def test_previous_live_regression():
    assert get_division_for_district("यवतमाळ") == "amravati"
    assert get_division_for_district("धुळे") == "nashik"
    assert get_division_for_district("पुणे") == "pune"

