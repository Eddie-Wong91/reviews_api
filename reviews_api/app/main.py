from datetime import date as ReviewDate
from pathlib import PurePosixPath

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictFields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Review(StrictFields):
    reviewId: str = Field(min_length=1, pattern=r"^\S+$")
    date: ReviewDate | None = None
    star: int | None = Field(None, ge=1, le=5)
    title: str | None = None
    content: str | None = None
    author: str | None = None
    purchased: bool | None = None
    vine: bool | None = None
    helpful: int | None = Field(None, ge=0)
    skus: list | None = None


class Batch(StrictFields):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: str = Field(min_length=1)
    requestId: str | None = None
    marketplace: str = Field(pattern=r"^[A-Z]{2}$")
    asin: str = Field(pattern=r"^[A-Z0-9]{10}$")
    collectedAt: AwareDatetime
    count: int = Field(ge=0, le=20)
    baselineBatchId: int | None = Field(None, gt=0)
    reviews: list[Review] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_file(self):
        parts = self.path.split("/")
        if (len(parts) != 2 or any(p in {"", ".", ".."} for p in parts)
                or "\\" in self.path or ":" in self.path
                or PurePosixPath(self.path).suffix.lower() != ".xlsx"):
            raise ValueError("Expected collection-directory/filename.xlsx")
        if self.count != len(self.reviews) or len({r.reviewId for r in self.reviews}) != self.count:
            raise ValueError("Review count mismatch or duplicate review ID")
        return self


INSERT_BATCH = """
    INSERT INTO amazon_reviews.import_batches
        (collection_dir, source_file_path, file_sha256, source, request_id,
         marketplace, asin, collected_at, review_count, baseline_batch_id, overlap_count, had_prior_reviews)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (collection_dir, file_sha256) DO NOTHING RETURNING id
"""
UPSERT_REVIEW = """
    INSERT INTO amazon_reviews.reviews AS r
        (marketplace, asin, review_id, review_date, star, title, content, author,
         purchased, vine, helpful, skus, collected_at, first_import_batch_id)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (marketplace, asin, review_id) DO UPDATE SET
        (review_date, star, title, content, author, purchased, vine, helpful, skus, collected_at) =
        (excluded.review_date, excluded.star, excluded.title, excluded.content, excluded.author,
         excluded.purchased, excluded.vine, excluded.helpful, excluded.skus, excluded.collected_at)
    WHERE (r.review_date, r.star, r.title, r.content, r.author, r.purchased, r.vine, r.helpful, r.skus)
        IS DISTINCT FROM
        (excluded.review_date, excluded.star, excluded.title, excluded.content, excluded.author,
         excluded.purchased, excluded.vine, excluded.helpful, excluded.skus)
"""


def connect():
    return psycopg.connect(connect_timeout=5)


app = FastAPI(title="Amazon Reviews API")


@app.get("/health/ready")
def ready():
    try:
        with connect() as db:
            db.execute("SELECT baseline_batch_id, overlap_count, had_prior_reviews FROM amazon_reviews.import_batches LIMIT 0")
            db.execute("SELECT first_import_batch_id FROM amazon_reviews.reviews LIMIT 0")
    except psycopg.Error:
        raise HTTPException(503, "Reviews database unavailable")
    return {"ready": True}


@app.post("/api/reviews/import")
def import_reviews(batch: Batch):
    folder = batch.path.split("/")[0]
    try:
        with connect() as db:
            # Serialize imports for this site/ASIN before allocating batch IDs.
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                       (batch.marketplace, batch.asin))
            baseline = batch.baselineBatchId
            if baseline is not None:
                root = db.execute("""
                    SELECT had_prior_reviews FROM amazon_reviews.import_batches
                    WHERE id=%s AND marketplace=%s AND asin=%s AND baseline_batch_id IS NULL
                        AND overlap_count IS NOT NULL
                """, (baseline, batch.marketplace, batch.asin)).fetchone()
                if root is None:
                    raise HTTPException(422, "Invalid baseline batch for this marketplace and ASIN")
                had_prior = root[0]
            else:
                had_prior = db.execute("""
                    SELECT EXISTS (SELECT 1 FROM amazon_reviews.reviews WHERE marketplace=%s AND asin=%s)
                """, (batch.marketplace, batch.asin)).fetchone()[0]
            overlap = db.execute("""
                SELECT count(*) FROM amazon_reviews.reviews
                WHERE marketplace=%s AND asin=%s AND review_id=ANY(%s::text[])
                    AND (%s::bigint IS NULL OR first_import_batch_id IS NULL OR first_import_batch_id < %s)
            """, (batch.marketplace, batch.asin, [r.reviewId for r in batch.reviews],
                  baseline, baseline)).fetchone()[0]
            row = db.execute(INSERT_BATCH, (folder, batch.path, batch.sha256, batch.source,
                             batch.requestId, batch.marketplace, batch.asin,
                             batch.collectedAt, batch.count, baseline, overlap, had_prior)).fetchone()
            replay = row is None
            if replay:
                batch_id, count, saved_baseline, overlap, had_prior = db.execute("""
                    SELECT id, review_count, baseline_batch_id, overlap_count, had_prior_reviews
                    FROM amazon_reviews.import_batches
                    WHERE collection_dir=%s AND file_sha256=%s
                """, (folder, batch.sha256)).fetchone()
                if saved_baseline != baseline:
                    raise HTTPException(409, "File already imported with a different baseline")
            else:
                batch_id, count = row[0], batch.count
                for r in sorted(batch.reviews, key=lambda item: item.reviewId):
                    db.execute(UPSERT_REVIEW, (
                        batch.marketplace, batch.asin, r.reviewId, r.date, r.star, r.title,
                        r.content, r.author, r.purchased, r.vine, r.helpful,
                        None if r.skus is None else Jsonb(r.skus), batch.collectedAt, batch_id,
                    ))
    except psycopg.Error:
        raise HTTPException(503, "Reviews database transaction failed")
    return {"batchId": batch_id, "sha256": batch.sha256, "count": count, "replayed": replay,
            "baselineBatchId": baseline, "overlapCount": overlap, "hadPriorReviews": had_prior}
