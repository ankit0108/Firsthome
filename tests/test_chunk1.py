import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract  # noqa: E402
import sources  # noqa: E402
from chunk1_source_test import address_key  # noqa: E402


class Price(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(extract.parse_price("$650,000"), (650000, 650000))
        self.assertEqual(extract.parse_price("$600,000 - $650,000"), (600000, 650000))
        self.assertEqual(extract.parse_price("$600k-$650k"), (600000, 650000))
        self.assertEqual(extract.parse_price("From $599,900"), (599900, 599900))
        self.assertEqual(extract.parse_price("Contact agent"), (None, None))
        self.assertEqual(extract.parse_price("Contact agent", 610000), (610000, 610000))


class Lot(unittest.TestCase):
    def test_field(self):
        self.assertEqual(extract.lot_from_field(350), 350)
        self.assertEqual(extract.lot_from_field("350m²"), 350)
        self.assertEqual(extract.lot_from_field("1,200 m2"), 1200)
        self.assertEqual(extract.lot_from_field({"value": 0.04, "unit": "ha"}), 400)
        self.assertIsNone(extract.lot_from_field("n/a"))

    def test_text(self):
        self.assertEqual(extract.lot_from_text("Titled land size of 350m2 ready to build"), 350)
        self.assertEqual(extract.lot_from_text("A 392 sqm corner block"), 392)
        self.assertEqual(extract.lot_from_text("Lot area: approx. 336 m²"), 336)
        self.assertIsNone(extract.lot_from_text("living area of 190m² on a quiet street"))


class Frontage(unittest.TestCase):
    def test_text(self):
        self.assertEqual(extract.frontage_from_text("Generous 12.5m frontage"), 12.5)
        self.assertEqual(extract.frontage_from_text("frontage of approx 14m"), 14)
        self.assertEqual(extract.frontage_from_text("Frontage: 10.5 m"), 10.5)
        self.assertEqual(extract.frontage_from_text("12.5 x 28m block"), 12.5)
        self.assertEqual(extract.frontage_from_text("12.5m x 28m"), 12.5)
        self.assertEqual(extract.frontage_from_text("a 14 metre wide lot"), 14)
        self.assertIsNone(extract.frontage_from_text("4 x 2 home, 350m2"))
        self.assertIsNone(extract.frontage_from_text("frontage to the park"))


class HouseSize(unittest.TestCase):
    def test_text(self):
        self.assertEqual(extract.house_squares_from_text("Spacious 22 squares of living"), 22)
        self.assertEqual(extract.house_squares_from_text("23.5sq home"), 23.5)
        self.assertEqual(extract.house_squares_from_text("total area 209.17m²"), 22.5)
        self.assertIsNone(extract.house_squares_from_text("350 sqm block"))
        self.assertIsNone(extract.house_squares_from_text("21 sq. m garden shed"))
        self.assertIsNone(extract.house_squares_from_text("square metres"))
        self.assertIsNone(extract.house_squares_from_text("lot of 350sq"))


class Kind(unittest.TestCase):
    def test_kind(self):
        self.assertEqual(extract.rough_kind("Land", "Titled now"), "land")
        self.assertEqual(extract.rough_kind("House", "Brand new house & land package"), "package")
        self.assertEqual(extract.rough_kind("House", "Never lived in"), "house")
        self.assertEqual(extract.rough_kind("Townhouse", ""), "townhouse")


class Mapping(unittest.TestCase):
    def test_scraper_a_shape(self):
        row = sources.normalise({
            "listingId": "152504952", "url": "https://x/1", "propertyType": "House",
            "priceText": "$699,000", "priceFrom": 699000,
            "address": "12 Sample St, Clyde North, Vic 3978", "suburb": "Clyde North",
            "bedrooms": 4, "bathrooms": 2, "parkingSpaces": 2, "landSize": "350m²",
            "description": "House and land package. 12.5m frontage, 22 squares.",
        }, "A")
        self.assertEqual(row["kind"], "package")
        self.assertEqual((row["price_low"], row["lot_m2"], row["frontage_m"], row["house_sq"]),
                         (699000, 350, 12.5, 22))

    def test_scraper_b_shape(self):
        row = sources.normalise({
            "propertyId": "148523671", "url": "https://x/2", "propertyType": "land",
            "address": {"full": "Lot 209 Sample Rd, Clyde North VIC 3978", "suburb": "Clyde North"},
            "price": {"display": "$385,000"},
            "features": {"bedrooms": None},
            "headline": "Titled 375m2 block", "description": "14 x 26.8m, ready to build",
            "propertyFeatures": ["Land size: 375m²"],
        }, "B")
        self.assertEqual(row["kind"], "land")
        self.assertEqual((row["price_low"], row["lot_m2"], row["frontage_m"]), (385000, 375, 14))
        self.assertEqual(row["suburb"], "Clyde North")


class Address(unittest.TestCase):
    def test_key(self):
        self.assertEqual(address_key("12 Sample Street, Clyde North VIC 3978"),
                         address_key("12 Sample St, Clyde North, Vic 3978"))
        self.assertIsNone(address_key("Address available on request"))


if __name__ == "__main__":
    unittest.main()
