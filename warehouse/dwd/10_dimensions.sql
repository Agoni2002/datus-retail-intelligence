DROP SCHEMA dwd CASCADE;
CREATE SCHEMA dwd;

CREATE TABLE dwd.dim_date (
    date_key DATE PRIMARY KEY, month_start DATE NOT NULL,
    year_number SMALLINT NOT NULL, month_number TINYINT NOT NULL, iso_weekday TINYINT NOT NULL
);
INSERT INTO dwd.dim_date
WITH events AS (
    SELECT unnest([order_purchase_timestamp, order_approved_at, order_delivered_carrier_date,
                   order_delivered_customer_date, order_estimated_delivery_date]) event_at FROM stg_orders
    UNION ALL
    SELECT shipping_limit_date FROM stg_order_items
    UNION ALL
    SELECT unnest([review_creation_date, review_answer_timestamp]) FROM stg_order_reviews
),
bounds AS (SELECT min(event_at)::DATE first_date, max(event_at)::DATE last_date FROM events)
SELECT day::DATE, date_trunc('month', day)::DATE, year(day), month(day), isodow(day)
FROM bounds, LATERAL generate_series(first_date, last_date, INTERVAL 1 DAY) AS dates(day);

CREATE TABLE dwd.dim_geography (
    zip_prefix VARCHAR PRIMARY KEY, city VARCHAR, state VARCHAR, latitude DOUBLE, longitude DOUBLE,
    geo_source VARCHAR NOT NULL
);
INSERT INTO dwd.dim_geography
WITH zip_names AS (
    SELECT geolocation_zip_code_prefix zip_prefix, lower(geolocation_city) city, upper(geolocation_state) state,
           median(geolocation_lat) latitude, median(geolocation_lng) longitude, 'geolocation' geo_source,
           1 priority, count(*) observations
    FROM stg_geolocation
    WHERE regexp_full_match(geolocation_zip_code_prefix, '[0-9]{5}')
      AND geolocation_lat BETWEEN -90 AND 90 AND geolocation_lng BETWEEN -180 AND 180
    GROUP BY 1, 2, 3
    UNION ALL
    SELECT zip_prefix, city, state, NULL, NULL, 'customer_or_seller', 2, count(*)
    FROM (
        SELECT customer_zip_code_prefix zip_prefix, lower(customer_city) city, upper(customer_state) state
        FROM stg_customers
        UNION ALL
        SELECT seller_zip_code_prefix, lower(seller_city), upper(seller_state) FROM stg_sellers
    ) GROUP BY 1, 2, 3
)
SELECT zip_prefix, city, state, latitude, longitude, geo_source
FROM zip_names
QUALIFY row_number() OVER (PARTITION BY zip_prefix
                           ORDER BY priority, observations DESC, state NULLS LAST, city NULLS LAST) = 1;

CREATE TABLE dwd.dim_customer (
    customer_id VARCHAR PRIMARY KEY, customer_unique_id VARCHAR NOT NULL,
    zip_prefix VARCHAR NOT NULL REFERENCES dwd.dim_geography(zip_prefix),
    city VARCHAR, state VARCHAR NOT NULL
);
INSERT INTO dwd.dim_customer
SELECT customer_id, customer_unique_id, customer_zip_code_prefix, lower(customer_city), upper(customer_state)
FROM stg_customers;

CREATE TABLE dwd.dim_seller (
    seller_id VARCHAR PRIMARY KEY, zip_prefix VARCHAR NOT NULL REFERENCES dwd.dim_geography(zip_prefix),
    city VARCHAR, state VARCHAR NOT NULL
);
INSERT INTO dwd.dim_seller
SELECT seller_id, seller_zip_code_prefix, lower(seller_city), upper(seller_state) FROM stg_sellers;

CREATE TABLE dwd.dim_product (
    product_id VARCHAR PRIMARY KEY, category_code VARCHAR NOT NULL, category_name VARCHAR NOT NULL,
    name_length INTEGER, description_length INTEGER, photo_count INTEGER,
    weight_g DOUBLE, length_cm DOUBLE, height_cm DOUBLE, width_cm DOUBLE
);
INSERT INTO dwd.dim_product
SELECT p.product_id, coalesce(p.product_category_name, '(unknown)'),
       coalesce(t.product_category_name_english, p.product_category_name, '(unknown)'),
       p.product_name_lenght, p.product_description_lenght, p.product_photos_qty,
       p.product_weight_g, p.product_length_cm, p.product_height_cm, p.product_width_cm
FROM stg_products p LEFT JOIN stg_product_category_name_translation t USING (product_category_name);
