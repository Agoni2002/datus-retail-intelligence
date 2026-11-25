"""Regenerate the small, independently authored Olist-shaped CSV fixture."""

import csv
from pathlib import Path

from ingestion.contract import SOURCES, source_filename

# o1 has two items, two payments and two distinct reviews. A direct join
# across those relations would inflate its 100 BRL merchandise total to 400.
ROWS = {
    "orders": [
        ("o1", "c1", "delivered", "2018-01-02 10:00:00", "2018-01-02 12:00:00",
         "2018-01-03 08:00:00", "2018-01-05 16:00:00", "2018-01-05 00:00:00"),
        ("o2", "c2", "delivered", "2018-01-07 10:00:00", "", "",
         "2018-01-13 16:00:00", "2018-01-10 00:00:00"),
        ("o3", "c3", "delivered", "2018-01-15 10:00:00", "", "", "2018-01-19 11:00:00", ""),
        ("o4", "c4", "canceled", "2018-01-22 10:00:00", "", "", "", ""),
        ("o5", "c5", "delivered", "2018-02-03 10:00:00", "", "",
         "2018-02-12 11:00:00", "2018-02-10 00:00:00"),
        ("o6", "c6", "unavailable", "2018-02-10 10:00:00", "", "", "", ""),
        ("o7", "c7", "canceled", "2018-02-14 10:00:00", "", "", "", ""),
    ],
    "order_items": [
        ("o1", 1, "p1", "s1", "2018-01-04 00:00:00", 60, 5),
        ("o1", 2, "p2", "s2", "2018-01-04 00:00:00", 40, 4),
        ("o2", 1, "p1", "s1", "2018-01-09 00:00:00", 50, 5),
        ("o3", 1, "p2", "s2", "2018-01-17 00:00:00", 50, 6),
        ("o4", 1, "p2", "s1", "", 25, 5),
        ("o5", 1, "p1", "s2", "2018-02-05 00:00:00", 80, 8),
        ("o7", 1, "p1", "s1", "", 10, 3),
        ("o7", 2, "p3", "s2", "", 20, 5),
    ],
    "customers": [
        ("c1", "u1", "01001", "São Paulo", "SP"), ("c2", "u1", "01001", "São Paulo", "SP"),
        ("c3", "u2", "20001", "Rio de Janeiro", "RJ"), ("c4", "u3", "20001", "Rio de Janeiro", "RJ"),
        ("c5", "u4", "20001", "Rio de Janeiro", "RJ"), ("c6", "u5", "30001", "Belo Horizonte", "MG"),
        ("c7", "u5", "30001", "Belo Horizonte", "MG"),
    ],
    "products": [
        ("p1", "eletronicos", 12, 27, 2, 350, 20, 4, 10),
        ("p2", "casa", 8, 35, 1, 850, 15, 20, 11),
        ("p3", "", "", "", "", "", "", "", ""),
    ],
    "sellers": [("s1", "01001", "São Paulo", "SP"), ("s2", "20001", "Rio de Janeiro", "RJ")],
    "order_payments": [
        ("o1", 1, "credit_card", 1, 90), ("o1", 2, "voucher", 1, 19),
        ("o2", 1, "boleto", 1, 55), ("o3", 1, "credit_card", 1, 56),
        ("o5", 1, "credit_card", 2, 88),
    ],
    "order_reviews": [
        ("r1", "o1", 2, "", "First note, before follow-up.", "2018-01-06 00:00:00", "2018-01-06 12:00:00"),
        ("r2", "o1", 5, "Updated", "Follow-up.\nAll good.", "2018-01-07 00:00:00", "2018-01-08 12:00:00"),
        ("r3", "o2", 3, "", "", "2018-01-14 00:00:00", "2018-01-15 12:00:00"),
        ("r4", "o5", 4, "", "", "2018-02-13 00:00:00", "2018-02-14 12:00:00"),
    ],
    "geolocation": [
        ("01001", -23.54, -46.63, "São Paulo", "SP"),
        ("01001", -23.55, -46.64, "São Paulo", "SP"),
        ("20001", -22.90, -43.17, "Rio de Janeiro", "RJ"),
    ],
    "product_category_name_translation": [("eletronicos", "electronics"), ("casa", "home")],
}


def generate(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in ROWS.items():
        with (directory / source_filename(name)).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(SOURCES[name].columns)
            writer.writerows(rows)


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent / "olist")
