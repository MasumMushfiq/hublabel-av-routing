import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from build_myki_commuters import parse_stop_ids


def test_parse_stop_ids_accepts_comma_separated_integers_with_whitespace():
    assert parse_stop_ids("18, 19980,21131 , 21132") == (
        18,
        19980,
        21131,
        21132,
    )


def test_parse_stop_ids_accepts_single_integer():
    assert parse_stop_ids("18") == (18,)


def test_parse_stop_ids_rejects_empty_values():
    for value in ("", "18,", "18,,19980", "18, ,19980"):
        try:
            parse_stop_ids(value)
        except argparse.ArgumentTypeError as exc:
            assert "empty value" in str(exc)
        else:
            raise AssertionError(f"expected argparse error for {value!r}")


def test_parse_stop_ids_rejects_non_integer_values():
    try:
        parse_stop_ids("18,abc,19980")
    except argparse.ArgumentTypeError as exc:
        assert "not an integer" in str(exc)
    else:
        raise AssertionError("expected argparse error for non-integer stop ID")
