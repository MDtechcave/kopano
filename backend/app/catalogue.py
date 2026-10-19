"""Loads the inventory CSV and turns it into clean product records.

The one rule: never invent product information. We only fix things we can prove
from the file itself, and every change is written to `data_notes` so it can be explained.
The original category and description are always kept next to the cleaned ones.
"""
import csv
import re
from pathlib import Path

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Stock bands. The public site shows a band, not the exact number.
# (low, high, key, label)  high=None means "no upper limit".
# ---------------------------------------------------------------------------
STOCK_BANDS = [
    (1, 2, "very_limited", "Very limited"),
    (3, 10, "limited", "Limited"),
    (11, 50, "in_stock", "In stock"),
    (51, None, "bulk", "Bulk stock"),
]
OUT_OF_STOCK = ("out_of_stock", "Out of stock")


def stock_band_for(quantity: int) -> tuple[str, str]:
    """Return (key, label) for a quantity."""
    if quantity <= 0:
        return OUT_OF_STOCK
    for low, high, key, label in STOCK_BANDS:
        if quantity >= low and (high is None or quantity <= high):
            return key, label
    return OUT_OF_STOCK


# ---------------------------------------------------------------------------
# Category cleaning.
# The CSV has a vague "Other" bucket and some products with no category at all.
# Those (and "Accessories", which mixes cables with boxes) are re-sorted using
# words that actually appear in the product description.
# ---------------------------------------------------------------------------
CATEGORY_NAMES = {
    "Batteries": "Batteries",
    "Lead-Acid Batteries": "Batteries",
    "Inverters": "Inverters",
    "Panels": "Solar Panels",
    "Industrial and Commercial Solar Systems": "Commercial & Industrial Systems",
    "Electric Bikes": "Electric Bikes",
    "UPS system": "UPS Systems",
    "All-in-One": "All-in-One Systems",
    "Hardware Tools": "Hardware Tools",
}

# Source categories that are too vague, so we look at the description instead.
CATEGORIES_TO_RESORT = {"", "Other", "Accessories"}

# Checked in order; the first match wins.
DESCRIPTION_RULES = [
    (("cable",), "Cables"),
    (("mounting system",), "Mounting Systems"),
    (("kelon", "btu"), "Air Conditioners"),
    (
        ("combiner box", "protection box", "disconnect box", "pre-wired box"),
        "Distribution & Protection Boxes",
    ),
]
FALLBACK_CATEGORY = "Accessories"

# ---------------------------------------------------------------------------
# Brands. We only report a brand when its name is written in the description.
# ---------------------------------------------------------------------------
BRAND_PATTERNS = [
    (r"\bdeye\b", "Deye"),
    (r"\bdyness\b", "Dyness"),
    (r"\blux ?power\b", "Luxpower"),
    (r"\bjinko\b", "Jinko"),
    (r"\bja\b", "JA Solar"),
    (r"\blongi\b", "Longi"),
    (r"\bsolax\b", "Solax"),
    (r"\bsrne\b", "SRNE"),
    (r"\bhina\b", "HINA"),
    (r"\bvolta\b", "Volta"),
    (r"\bshoto\b", "Shoto"),
    (r"\blemoen\b", "Lemoen"),
    (r"\bkelon\b", "Kelon"),
    (r"\bcnbm\b", "CNBM"),
    (r"\bgotion\b", "Gotion"),
    (r"\bkool energy\b", "Kool Energy"),
    (r"\bcool energy\b", "Cool Energy"),
    (r"\boliter\b", "Oliter"),
    (r"\bpylon\b", "Pylon"),
]

# Obvious typos only. Each fix is recorded in the product's data_notes.
TYPO_FIXES = {
    "BIFICIAL": "BIFACIAL",
    "dISC brakeH": "disc brake",
    "inverte rSUN": "inverter SUN",
    "R esidential": "Residential",
}


class Product(BaseModel):
    code: str
    description: str  # cleaned text shown on the site
    description_original: str  # exactly as supplied
    category: str  # cleaned category
    category_original: str  # exactly as supplied ("" if blank)
    brand: str | None
    quantity: int | None  # hidden from anonymous visitors
    stock_band: str
    stock_label: str
    data_notes: list[str]


class LoadReport(BaseModel):
    """A summary of what happened while reading the file. Handy for the write-up."""

    rows_read: int = 0
    products_loaded: int = 0
    rows_skipped_blank_code: int = 0
    rows_skipped_inactive: int = 0
    categories_resorted: int = 0
    typos_fixed: int = 0
    products_with_notes: int = 0


def clean_description(code: str, description: str, category: str, notes: list[str]) -> str:
    text = " ".join(description.split())  # collapse stray whitespace

    # Two rows are just called "Hardware Tools", which tells the buyer nothing.
    if text.lower() == category.strip().lower():
        notes.append("No product description was supplied in the inventory report.")
        return f"{text} (details to be confirmed)"

    for wrong, right in TYPO_FIXES.items():
        if wrong in text:
            text = text.replace(wrong, right)
            notes.append(f"Typo corrected: '{wrong}' -> '{right}'.")
    return text


def clean_category(original: str, description: str, notes: list[str]) -> str:
    if original not in CATEGORIES_TO_RESORT:
        return CATEGORY_NAMES.get(original, original)

    lowered = description.lower()
    matched = True
    for keywords, category in DESCRIPTION_RULES:
        if any(word in lowered for word in keywords):
            break
    else:
        category, matched = FALLBACK_CATEGORY, False

    if original != category:
        shown = original or "(blank)"
        reason = "using the description" if matched else "because the description gave no clearer match"
        notes.append(f"Source category {shown} re-sorted to '{category}' {reason}.")
    return category


def find_brand(description: str) -> str | None:
    lowered = description.lower()
    for pattern, brand in BRAND_PATTERNS:
        if re.search(pattern, lowered):
            return brand
    return None


def load_products(csv_path: Path) -> tuple[list[Product], LoadReport]:
    report = LoadReport()
    products: list[Product] = []

    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        lines = file.read().splitlines()

    # Excel adds a "sep=," line at the top; it is not data.
    if lines and lines[0].lower().startswith("sep="):
        lines = lines[1:]

    for row in csv.DictReader(lines):
        report.rows_read += 1
        code = (row.get("Code") or "").strip()

        # The file ends with a blank row and a grand total row (no code). Skip both.
        if not code:
            report.rows_skipped_blank_code += 1
            continue
        if (row.get("Active") or "").strip().lower() != "yes":
            report.rows_skipped_inactive += 1
            continue

        notes: list[str] = []
        category_original = (row.get("Category") or "").strip()
        description_original = (row.get("Description") or "").strip()

        description = clean_description(code, description_original, category_original, notes)
        category = clean_category(category_original, description_original, notes)
        quantity = int(row["Qty on Hand"])
        band_key, band_label = stock_band_for(quantity)

        if category_original in CATEGORIES_TO_RESORT and category != category_original:
            report.categories_resorted += 1
        report.typos_fixed += sum(1 for note in notes if note.startswith("Typo"))
        if notes:
            report.products_with_notes += 1

        products.append(
            Product(
                code=code,
                description=description,
                description_original=description_original,
                category=category,
                category_original=category_original,
                brand=find_brand(description_original),
                quantity=quantity,
                stock_band=band_key,
                stock_label=band_label,
                data_notes=notes,
            )
        )

    report.products_loaded = len(products)
    return products, report


class Catalogue:
    """Holds every product in memory. The list is small and read-only, so no database is needed."""

    def __init__(self, products: list[Product], report: LoadReport):
        self.products = products
        self.report = report
        self._by_code = {product.code: product for product in products}

    def get(self, code: str) -> Product | None:
        return self._by_code.get(code)

    def search(
        self,
        text: str = "",
        category: str | None = None,
        brand: str | None = None,
        stock_band: str | None = None,
        sort: str = "code",
    ) -> list[Product]:
        results = self.products

        # Every word the buyer types must appear in the code, description or brand.
        for word in text.lower().split():
            results = [
                p
                for p in results
                if word in p.code.lower()
                or word in p.description.lower()
                or word in (p.brand or "").lower()
            ]
        if category:
            results = [p for p in results if p.category == category]
        if brand:
            results = [p for p in results if p.brand == brand]
        if stock_band:
            results = [p for p in results if p.stock_band == stock_band]

        if sort == "stock_desc":
            return sorted(results, key=lambda p: -(p.quantity or 0))
        if sort == "stock_asc":
            return sorted(results, key=lambda p: p.quantity or 0)
        if sort == "name":
            return sorted(results, key=lambda p: p.description.lower())
        return sorted(results, key=lambda p: p.code)

    def facets(self) -> dict:
        """Counts for the filter sidebar."""

        def count(values):
            counts: dict[str, int] = {}
            for value in values:
                if value:
                    counts[value] = counts.get(value, 0) + 1
            return [{"name": name, "count": n} for name, n in sorted(counts.items())]

        bands = []
        for _, _, key, label in STOCK_BANDS:
            bands.append(
                {"key": key, "label": label, "count": sum(1 for p in self.products if p.stock_band == key)}
            )
        return {
            "categories": count(p.category for p in self.products),
            "brands": count(p.brand for p in self.products),
            "stock_bands": bands,
        }
