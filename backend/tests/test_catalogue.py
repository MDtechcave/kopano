"""Checks that the CSV is read and cleaned the way we say it is."""
from pathlib import Path

import pytest

from app.catalogue import load_products, stock_band_for

CSV = Path(__file__).resolve().parent.parent / "data" / "inventory.csv"


@pytest.fixture(scope="module")
def loaded():
    return load_products(CSV)


def test_blank_and_total_rows_are_skipped(loaded):
    products, report = loaded
    assert len(products) == 117
    assert report.rows_skipped_blank_code == 2


def test_stock_bands_add_up(loaded):
    products, _ = loaded
    counts = {}
    for product in products:
        counts[product.stock_band] = counts.get(product.stock_band, 0) + 1
    assert counts == {"very_limited": 25, "limited": 36, "in_stock": 40, "bulk": 16}


def test_band_edges():
    assert stock_band_for(2)[0] == "very_limited"
    assert stock_band_for(3)[0] == "limited"
    assert stock_band_for(10)[0] == "limited"
    assert stock_band_for(11)[0] == "in_stock"
    assert stock_band_for(50)[0] == "in_stock"
    assert stock_band_for(51)[0] == "bulk"
    assert stock_band_for(0)[0] == "out_of_stock"


def test_vague_categories_are_gone_but_originals_are_kept(loaded):
    products, _ = loaded
    assert not any(p.category in ("Other", "") for p in products)
    assert sum(1 for p in products if p.category_original == "Other") == 19


def test_blank_category_item_is_sorted_from_its_description(loaded):
    products, _ = loaded
    cable = next(p for p in loaded[0] if p.code == "HNPC0001")
    assert cable.category_original == ""
    assert cable.category == "Cables"
    assert cable.data_notes


def test_hardware_tools_rows_are_flagged_not_guessed(loaded):
    products, _ = loaded
    for code in ("TFS0378", "TSH001"):
        product = next(p for p in products if p.code == code)
        assert "No product description" in product.data_notes[0]
        assert product.description_original == "Hardware Tools"


def test_brand_only_when_written_in_description(loaded):
    products, _ = loaded
    assert next(p for p in products if p.code == "SPL540W").brand == "Longi"
    assert next(p for p in products if p.code == "SXIN7500").brand is None  # "X1 HYBRID 7.5D" names no brand
