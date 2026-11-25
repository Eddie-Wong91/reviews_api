BEGIN;
-- NULL first_import_batch_id identifies reviews present before this migration.
ALTER TABLE amazon_reviews.reviews
    ADD COLUMN first_import_batch_id bigint REFERENCES amazon_reviews.import_batches(id);
ALTER TABLE amazon_reviews.import_batches
    ADD COLUMN baseline_batch_id bigint REFERENCES amazon_reviews.import_batches(id),
    ADD COLUMN overlap_count integer CHECK (overlap_count BETWEEN 0 AND review_count),
    ADD COLUMN had_prior_reviews boolean;
COMMIT;
