CREATE TABLE dwd.fact_order (
    order_id VARCHAR PRIMARY KEY, customer_id VARCHAR NOT NULL REFERENCES dwd.dim_customer(customer_id),
    purchase_date DATE NOT NULL REFERENCES dwd.dim_date(date_key), status VARCHAR NOT NULL,
    purchased_at TIMESTAMP NOT NULL, approved_at TIMESTAMP, carrier_at TIMESTAMP, delivered_at TIMESTAMP,
    estimated_delivery_at TIMESTAMP, item_count BIGINT NOT NULL, merchandise_brl DECIMAL(24,2) NOT NULL,
    freight_brl DECIMAL(24,2) NOT NULL, payment_brl DECIMAL(24,2),
    latest_review_score INTEGER, delivery_eligible BOOLEAN NOT NULL, is_on_time BOOLEAN, late_days BIGINT,
    CHECK (item_count >= 0 AND merchandise_brl >= 0 AND freight_brl >= 0)
);
INSERT INTO dwd.fact_order
WITH items AS (
    SELECT order_id, count(*) item_count, sum(price) merchandise_brl, sum(freight_value) freight_brl
    FROM stg_order_items GROUP BY order_id
),
payments AS (
    SELECT order_id, sum(payment_value) payment_brl FROM stg_order_payments GROUP BY order_id
),
reviews AS (
    SELECT order_id, review_score
    FROM stg_order_reviews
    QUALIFY row_number() OVER (PARTITION BY order_id
        ORDER BY review_answer_timestamp DESC NULLS LAST, review_creation_date DESC NULLS LAST, review_id DESC) = 1
),
orders AS (
    SELECT *, order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
        AND order_estimated_delivery_date IS NOT NULL
        AND order_delivered_customer_date >= order_purchase_timestamp
        AND order_estimated_delivery_date::DATE >= order_purchase_timestamp::DATE
        AND (order_delivered_carrier_date IS NULL OR (order_delivered_carrier_date >= order_purchase_timestamp
             AND order_delivered_customer_date >= order_delivered_carrier_date))
        AND (order_approved_at IS NULL OR order_approved_at >= order_purchase_timestamp) AS eligible
    FROM stg_orders
)
SELECT o.order_id, o.customer_id, o.order_purchase_timestamp::DATE, o.order_status, o.order_purchase_timestamp,
       o.order_approved_at, o.order_delivered_carrier_date, o.order_delivered_customer_date,
       o.order_estimated_delivery_date, coalesce(i.item_count, 0), coalesce(i.merchandise_brl, 0),
       coalesce(i.freight_brl, 0), p.payment_brl, r.review_score, o.eligible,
       CASE WHEN o.eligible THEN o.order_delivered_customer_date::DATE <= o.order_estimated_delivery_date::DATE END,
       CASE WHEN o.eligible THEN greatest(0, date_diff('day', o.order_estimated_delivery_date::DATE,
                                                       o.order_delivered_customer_date::DATE)) END
FROM orders o LEFT JOIN items i USING (order_id) LEFT JOIN payments p USING (order_id)
LEFT JOIN reviews r USING (order_id);

CREATE TABLE dwd.fact_order_item (
    order_id VARCHAR REFERENCES dwd.fact_order(order_id), order_item_id INTEGER CHECK(order_item_id > 0),
    product_id VARCHAR NOT NULL REFERENCES dwd.dim_product(product_id),
    seller_id VARCHAR NOT NULL REFERENCES dwd.dim_seller(seller_id),
    shipping_limit_at TIMESTAMP, price_brl DECIMAL(18,2) NOT NULL CHECK(price_brl >= 0),
    freight_brl DECIMAL(18,2) NOT NULL CHECK(freight_brl >= 0),
    PRIMARY KEY(order_id, order_item_id)
);
INSERT INTO dwd.fact_order_item SELECT order_id, order_item_id, product_id, seller_id, shipping_limit_date,
    price, freight_value FROM stg_order_items;

CREATE TABLE dwd.fact_payment (
    order_id VARCHAR REFERENCES dwd.fact_order(order_id), payment_sequence INTEGER CHECK(payment_sequence > 0),
    payment_type VARCHAR NOT NULL, installments INTEGER CHECK(installments >= 0),
    payment_brl DECIMAL(18,2) NOT NULL CHECK(payment_brl >= 0), PRIMARY KEY(order_id, payment_sequence)
);
INSERT INTO dwd.fact_payment SELECT order_id, payment_sequential, payment_type, payment_installments,
    payment_value FROM stg_order_payments;

CREATE TABLE dwd.fact_review (
    order_id VARCHAR REFERENCES dwd.fact_order(order_id), review_id VARCHAR,
    score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5), comment_title VARCHAR, comment_message VARCHAR,
    created_at TIMESTAMP, answered_at TIMESTAMP, PRIMARY KEY(order_id, review_id)
);
INSERT INTO dwd.fact_review SELECT order_id, review_id, review_score, review_comment_title, review_comment_message,
    review_creation_date, review_answer_timestamp FROM stg_order_reviews;
