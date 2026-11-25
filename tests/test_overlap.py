import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from reviews_api.app import main as api

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_reviews import append_followup


def make_batch(baseline=None):
    return api.Batch(path="folder/reviews.xlsx", sha256="a" * 64, source="test",
                     marketplace="US", asin="B0FNWJYJBV", collectedAt="2026-11-25T09:00:00+08:00",
                     count=1, reviews=[{"reviewId": "A", "star": 5}], baselineBatchId=baseline)


class ImportTests(unittest.TestCase):
    def run_import(self, batch, db_rows):
        connection = MagicMock()
        db = connection.__enter__.return_value
        db.execute.side_effect = [MagicMock(fetchone=lambda r=row: r) for row in db_rows]
        with patch.object(api, "connect", return_value=connection):
            result = api.import_reviews(batch)
        return result, db

    def test_baseline_and_first_import(self):
        result, db = self.run_import(make_batch(10), [None, (True,), (0,), (12,), None])
        self.assertEqual((result["batchId"], result["overlapCount"]), (12, 0))
        sql, params = db.execute.call_args_list[2].args
        self.assertIn("first_import_batch_id < %s", sql)
        self.assertIn("first_import_batch_id IS NULL", sql)
        self.assertEqual(params, ("US", "B0FNWJYJBV", ["A"], 10, 10))
        self.assertEqual(db.execute.call_args_list[-1].args[1][-1], 12)

    def test_first_import_and_replay(self):
        first, _ = self.run_import(make_batch(), [None, (False,), (0,), (10,), None])
        replay, _ = self.run_import(make_batch(), [None, (True,), (1,), None, (10, 1, None, 0, False)])
        self.assertEqual(replay, {**first, "replayed": True})
        self.assertFalse(first["hadPriorReviews"])

    def test_invalid_and_changed_baseline(self):
        with self.assertRaises(api.HTTPException) as error:
            self.run_import(make_batch(10), [None, None])
        self.assertEqual(error.exception.status_code, 422)
        with self.assertRaises(api.HTTPException) as error:
            self.run_import(make_batch(10), [None, (True,), (0,), None, (12, 1, None, 0, False)])
        self.assertEqual(error.exception.status_code, 409)

    def test_followup_log(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch = make_batch().model_dump()
            receipt = dict(batchId=12, baselineBatchId=10, count=19, overlapCount=0)
            append_followup(root, batch, receipt, 5, False)
            self.assertFalse((root / "follow-up").exists())
            receipt["count"] = 20
            append_followup(root, batch, receipt, 5, False)
            append_followup(root, batch, receipt, 5, False)
            append_followup(root, batch, {**receipt, "count": 5, "batchId": 13}, 5, True)
            append_followup(root, batch, {**receipt, "overlapCount": 2, "batchId": 14}, 5, True)
            events = [json.loads(line) for p in (root / "follow-up").glob("*.jsonl")
                      for line in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([e["status"] for e in events], ["疑似缺口", "未满上限，未衔接", "已衔接"])
            self.assertTrue(all(e["baselineBatchId"] == 10 for e in events))
