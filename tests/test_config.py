from config import PARAMETER_ALIASES, PARAMETER_CATALOG, PARAMETER_DISPLAY_NAMES


def test_wob_exists_in_parameter_aliases():
    assert "WOB" in PARAMETER_ALIASES
    assert "WOB" in PARAMETER_CATALOG
    assert "WOB" in PARAMETER_DISPLAY_NAMES


def test_bit_depth_uses_bit_depth_mnemonics():
    aliases = PARAMETER_ALIASES["Bit Depth"]

    assert "BDTI" in aliases
    assert "BITD" in aliases
    assert "BIT_DEPTH" in aliases


def test_well_depth_uses_real_depth_candidates():
    aliases = PARAMETER_ALIASES["Well Depth"]

    expected_candidates = {
        "GS_DMEA",
        "DMEA",
        "DEPT",
        "GS_DVER",
        "DVER",
        "DBTV",
        "GS_DBTM",
        "DBTM",
    }

    assert expected_candidates.intersection(set(aliases))


def test_no_old_well_depth_dbtm_label_remains():
    assert "Well Depth (DBTM)" not in PARAMETER_ALIASES
    assert "Well Depth (DBTM)" not in PARAMETER_CATALOG
    assert "Well Depth (DBTM)" not in PARAMETER_DISPLAY_NAMES


def test_catalog_has_logical_ranges_for_all_alias_labels():
    for label in PARAMETER_ALIASES:
        assert label in PARAMETER_CATALOG
        assert "logical_min" in PARAMETER_CATALOG[label]
        assert "logical_max" in PARAMETER_CATALOG[label]