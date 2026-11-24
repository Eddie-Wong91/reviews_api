BEGIN;
CREATE SCHEMA IF NOT EXISTS amazon_reviews;
CREATE TABLE IF NOT EXISTS amazon_reviews.import_batches (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collection_dir text NOT NULL,
    source_file_path text NOT NULL,
    file_sha256 text NOT NULL,
    source text NOT NULL,
    request_id text,
    marketplace text NOT NULL,
    asin text NOT NULL,
    collected_at timestamptz NOT NULL,
    review_count integer NOT NULL CHECK (review_count BETWEEN 0 AND 20),
    imported_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (collection_dir, file_sha256)
);
CREATE TABLE IF NOT EXISTS amazon_reviews.reviews (
    marketplace text NOT NULL,
    asin text NOT NULL,
    review_id text NOT NULL,
    review_date date,
    star smallint CHECK (star BETWEEN 1 AND 5),
    title text,
    content text,
    author text,
    purchased boolean,
    vine boolean,
    helpful integer CHECK (helpful >= 0),
    skus jsonb,
    collected_at timestamptz NOT NULL,
    PRIMARY KEY (marketplace, asin, review_id)
);
COMMIT;
