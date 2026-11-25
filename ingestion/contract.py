"""Olist v6 CSV contract. All source fields land as text before conversion."""

from dataclasses import dataclass

TEXT = "VARCHAR"
INT = "INTEGER"
MONEY = "DECIMAL(18,2)"
TS = "TIMESTAMP"
REAL = "DOUBLE"


@dataclass(frozen=True)
class Source:
    columns: dict[str, str]
    key: tuple[str, ...]
    required: tuple[str, ...]
    newest: tuple[str, ...] = ()
    filename: str = ""


def fields(spec: str) -> dict[str, str]:
    types = {"text": TEXT, "int": INT, "money": MONEY, "ts": TS, "real": REAL}
    return {name: types[kind] for name, kind in (item.split(":") for item in spec.split())}


SOURCES = {
    "orders": Source(fields("""
        order_id:text customer_id:text order_status:text order_purchase_timestamp:ts
        order_approved_at:ts order_delivered_carrier_date:ts order_delivered_customer_date:ts
        order_estimated_delivery_date:ts
    """), ("order_id",), ("customer_id", "order_status", "order_purchase_timestamp"),
        ("order_delivered_customer_date", "order_delivered_carrier_date", "order_approved_at", "order_purchase_timestamp")),
    "order_items": Source(fields("""
        order_id:text order_item_id:int product_id:text seller_id:text shipping_limit_date:ts
        price:money freight_value:money
    """), ("order_id", "order_item_id"), ("product_id", "seller_id", "price", "freight_value"),
        ("shipping_limit_date",)),
    "customers": Source(fields("""
        customer_id:text customer_unique_id:text customer_zip_code_prefix:text customer_city:text customer_state:text
    """), ("customer_id",), ("customer_unique_id", "customer_zip_code_prefix", "customer_state")),
    "products": Source(fields("""
        product_id:text product_category_name:text product_name_lenght:int product_description_lenght:int
        product_photos_qty:int product_weight_g:real product_length_cm:real product_height_cm:real product_width_cm:real
    """), ("product_id",), ()),
    "sellers": Source(fields("""
        seller_id:text seller_zip_code_prefix:text seller_city:text seller_state:text
    """), ("seller_id",), ("seller_zip_code_prefix", "seller_state")),
    "order_payments": Source(fields("""
        order_id:text payment_sequential:int payment_type:text payment_installments:int payment_value:money
    """), ("order_id", "payment_sequential"), ("payment_type", "payment_value")),
    "order_reviews": Source(fields("""
        review_id:text order_id:text review_score:int review_comment_title:text review_comment_message:text
        review_creation_date:ts review_answer_timestamp:ts
    """), ("order_id", "review_id"), ("review_score",), ("review_answer_timestamp", "review_creation_date")),
    "geolocation": Source(fields("""
        geolocation_zip_code_prefix:text geolocation_lat:real geolocation_lng:real
        geolocation_city:text geolocation_state:text
    """), ("geolocation_zip_code_prefix", "geolocation_lat", "geolocation_lng",
           "geolocation_city", "geolocation_state"), ()),
    "product_category_name_translation": Source(fields("""
        product_category_name:text product_category_name_english:text
    """), ("product_category_name",), ("product_category_name_english",),
        filename="product_category_name_translation.csv"),
}

RELATIONSHIPS = (
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("order_payments", "order_id", "orders", "order_id"),
    ("order_reviews", "order_id", "orders", "order_id"),
)
OPTIONAL_RELATIONSHIPS = (
    ("products", "product_category_name", "product_category_name_translation", "product_category_name"),
    ("customers", "customer_zip_code_prefix", "geolocation", "geolocation_zip_code_prefix"),
    ("sellers", "seller_zip_code_prefix", "geolocation", "geolocation_zip_code_prefix"),
)


def source_filename(name: str) -> str:
    return SOURCES[name].filename or f"olist_{name}_dataset.csv"


def identifier(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def text_value(column):
    # Trim identifiers and typed input. Preserve source review text verbatim.
    col = identifier(column)
    if column.startswith("review_comment_"):
        return f"nullif({col}, '')"
    return f"nullif(trim({col}), '')"


def typed_value(column, kind):
    raw = text_value(column)
    if kind == TEXT:
        if column.endswith("_zip_code_prefix"):
            return f"CASE WHEN regexp_full_match({raw}, '[0-9]{{1,5}}') THEN lpad({raw}, 5, '0') ELSE {raw} END"
        return raw
    if kind == INT:
        return rf"""CASE WHEN regexp_full_match({raw}, '[+-]?[0-9]+(\.0+)?')
                        THEN try_cast({raw} AS INTEGER) END"""
    if kind == MONEY:
        return rf"""CASE WHEN regexp_full_match({raw}, '[+-]?[0-9]+(\.[0-9]{{1,2}}0*)?')
                        THEN try_cast({raw} AS {kind}) END"""
    return f"try_cast({raw} AS {kind})"
