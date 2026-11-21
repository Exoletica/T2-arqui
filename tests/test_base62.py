import pytest

from app.base62 import decode, encode

SAMPLE_IDS = [0, 1, 61, 62, 3843, 238328, 597652313, 10**9]


@pytest.mark.parametrize("number", SAMPLE_IDS)
def test_roundtrip(number):
    assert decode(encode(number)) == number


def test_start_id_encodes_to_five_chars():
    assert encode(597652313) == "eRgfR"
    assert len(encode(597652313)) == 5


def test_hashes_are_unique_and_monotonic():
    hashes = [encode(n) for n in range(597652313, 597652413)]
    assert len(hashes) == len(set(hashes))


def test_negative_number_is_rejected():
    with pytest.raises(ValueError):
        encode(-1)


def test_invalid_hash_is_rejected():
    with pytest.raises(ValueError):
        decode("abc-123")
