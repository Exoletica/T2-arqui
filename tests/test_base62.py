import pytest

import base62

SAMPLE_IDS = [0, 1, 61, 62, 3843, 238328, 597652313, 10**9]


@pytest.mark.parametrize("number", SAMPLE_IDS)
def test_roundtrip(number):
    assert base62.decode(base62.encode(number)) == number


def test_start_id_encodes_to_five_chars():
    assert base62.encode(597652313) == "eRgfR"
    assert len(base62.encode(597652313)) == 5


def test_hashes_are_unique_and_monotonic():
    hashes = [base62.encode(n) for n in range(597652313, 597652413)]
    assert len(hashes) == len(set(hashes))
    assert [base62.decode(h) for h in hashes] == list(range(597652313, 597652413))


def test_library_behavior_for_negative_and_empty_values():
    assert base62.encode(-1) == "0"
    assert base62.decode("") == 0


def test_invalid_hash_is_rejected():
    with pytest.raises(ValueError):
        base62.decode("abc-123")


@pytest.mark.parametrize("number,legacy_hash", [
    (0, "0"), (1, "1"), (61, "z"), (62, "10"), (3843, "zz"),
    (238328, "1000"), (597652313, "eRgfR"), (597652314, "eRgfS"),
    (597652315, "eRgfT"), (1000000000, "15ftgG"),
])
def test_legacy_hash_compatibility(number, legacy_hash):
    assert base62.encode(number) == legacy_hash
    assert base62.decode(legacy_hash) == number


@pytest.mark.parametrize("value", [1.5, "1"])
def test_library_rejects_non_integer_ids(value):
    with pytest.raises(TypeError):
        base62.encode(value)


def test_uses_installed_pybase62():
    from importlib.metadata import distribution
    from pathlib import Path
    from app import urls

    package = distribution("pybase62")
    assert package.version == "1.0.0"
    assert Path(base62.__file__).resolve() == Path(package.locate_file("base62.py")).resolve()
    assert urls.base62 is base62
