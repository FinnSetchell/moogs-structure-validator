from utils.nbt_versions import _parse_range, _parse_version, _version_in_range


def test_parse_version():
    assert _parse_version("1.21") == (1, 21)
    assert _parse_version("1.21.4") == (1, 21, 4)
    assert _parse_version("26.2") == (26, 2)


def test_parse_range_single():
    assert _parse_range("1.21") == ((1, 21), (1, 21))


def test_parse_range_two_sided():
    assert _parse_range("1.21-1.21.4") == ((1, 21), (1, 21, 4))


def test_parse_range_malformed():
    assert _parse_range("nonsense") is None
    assert _parse_range("1.21-") is None
    assert _parse_range("1.a") is None


def test_parse_range_inverted():
    # Inverted still parses; callers reject via low > high check.
    assert _parse_range("1.21.4-1.21") == ((1, 21, 4), (1, 21))


def test_version_in_range_inclusive_both_ends():
    assert _version_in_range("1.21", "1.21-1.21.4")
    assert _version_in_range("1.21.4", "1.21-1.21.4")
    assert _version_in_range("1.21.2", "1.21-1.21.4")


def test_version_in_range_excludes_out_of_bounds():
    assert not _version_in_range("1.20.5", "1.21-1.21.4")
    assert not _version_in_range("1.21.5", "1.21-1.21.4")


def test_version_in_range_single_key():
    assert _version_in_range("1.21", "1.21")
    assert not _version_in_range("1.21.1", "1.21")
