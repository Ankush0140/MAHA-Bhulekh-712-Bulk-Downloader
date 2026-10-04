import pytest
from pathlib import Path
from app.services.filename import sanitize_filename_component, build_output_filepath
from app.models.location import LocationSelection

def test_sanitize_simple_numeric():
    assert sanitize_filename_component("1") == "1"

def test_sanitize_slash_subdivision():
    result = sanitize_filename_component("115/1/A")
    assert result == "115-1-A"

def test_sanitize_devanagari_characters():
    assert sanitize_filename_component("17/10/ए") == "17-10-ए"
    assert sanitize_filename_component("17/11/बी") == "17-11-बी"

def test_path_traversal_prevention():
    assert sanitize_filename_component("../path/traversal") == "path-traversal"

def test_illegal_windows_characters():
    assert sanitize_filename_component('<illegal>:name*"|?') == "illegal-name"

def test_build_output_filepath_same_division_district(tmp_path):
    loc = LocationSelection(
        division_text="Pune", division_value=None, district_text="Pune", district_value="1",
        taluka_text="Maval", taluka_value="2", village_text="Shivali", village_value="3"
    )
    output_file = build_output_filepath(loc, "115/1/A", tmp_path)
    assert output_file.parent == tmp_path / "Pune" / "Maval" / "Shivali"
    assert output_file.name == "Pune_Maval_Shivali_115-1-A.pdf"

def test_build_output_filepath_distinct_division_district(tmp_path):
    loc = LocationSelection(
        division_text="Konkan", division_value=None, district_text="Thane", district_value="1",
        taluka_text="Kalyan", taluka_value="2", village_text="VillageA", village_value="3"
    )
    output_file = build_output_filepath(loc, "10", tmp_path)
    assert output_file.parent == tmp_path / "Thane" / "Kalyan" / "VillageA"
    assert output_file.name == "Thane_Kalyan_VillageA_10.pdf"

def test_build_output_filepath_missing_division(tmp_path):
    loc = LocationSelection(
        division_text=None, division_value=None, district_text="वाशिम", district_value="1",
        taluka_text="मानोरा", taluka_value="2", village_text="आमगव्हाण", village_value="3"
    )
    output_file = build_output_filepath(loc, "109", tmp_path)
    
    # Assert missing division does not produce 'unnamed' or 'unknown'
    assert "unnamed" not in str(output_file).lower()
    assert "unknown" not in str(output_file).lower()
    
    # Assert missing division produces exactly: output/District/Taluka/Village/file.pdf
    expected_parent = tmp_path / "वाशिम" / "मानोरा" / "आमगव्हाण"
    assert output_file.parent == expected_parent
    assert output_file.name == "वाशिम_मानोरा_आमगव्हाण_109.pdf"

def test_missing_fields_fail(tmp_path):
    # missing district
    with pytest.raises(ValueError, match="LOCATION_SELECTION_UNAVAILABLE"):
        build_output_filepath(LocationSelection("","1","T","2","V","3",None,None), "1", tmp_path)
    # missing taluka
    with pytest.raises(ValueError, match="LOCATION_SELECTION_UNAVAILABLE"):
        build_output_filepath(LocationSelection("D","1","","2","V","3",None,None), "1", tmp_path)
    # missing village
    with pytest.raises(ValueError, match="LOCATION_SELECTION_UNAVAILABLE"):
        build_output_filepath(LocationSelection("D","1","T","2","","3",None,None), "1", tmp_path)
    # missing survey
    with pytest.raises(ValueError, match="SURVEY_IDENTIFIER_UNAVAILABLE"):
        build_output_filepath(LocationSelection("D","1","T","2","V","3",None,None), "", tmp_path)

def test_changing_fields_changes_path(tmp_path):
    loc1 = LocationSelection(district_text="D1", district_value="1", taluka_text="T1", taluka_value="2", village_text="V1", village_value="3", division_text=None, division_value=None)
    loc2 = LocationSelection(district_text="D2", district_value="1", taluka_text="T2", taluka_value="2", village_text="V2", village_value="3", division_text=None, division_value=None)
    p1 = build_output_filepath(loc1, "1", tmp_path)
    p2 = build_output_filepath(loc2, "1", tmp_path)
    assert p1.parent != p2.parent
    assert p1.name != p2.name

def test_collision_protection(tmp_path):
    loc = LocationSelection(district_text="D", district_value="1", taluka_text="T", taluka_value="2", village_text="V", village_value="3", division_text=None, division_value=None)
    p1 = build_output_filepath(loc, "10/1/1", tmp_path)
    p1.touch()  # mock the file creation
    
    # Same exact original record should be allowed (returns same path)
    p2 = build_output_filepath(loc, "10/1/1", tmp_path)
    assert p1 == p2
    
    # Different original record that sanitizes to the same safe string
    with pytest.raises(FileExistsError, match="Collision detected for 10\\\\1\\\\1"):
        build_output_filepath(loc, "10\\1\\1", tmp_path)

def test_devanagari_location_names(tmp_path):
    loc = LocationSelection(district_text="पुणे", district_value="1", taluka_text="मावळ", taluka_value="2", village_text="शिवाळी", village_value="3", division_text=None, division_value=None)
    out = build_output_filepath(loc, "१", tmp_path)
    assert "पुणे" in str(out)
    assert "मावळ" in str(out)
    assert "शिवाळी" in str(out)
    assert "१" in str(out)
