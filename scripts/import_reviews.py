import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from review_workbook import read_batch


def followup_status(count, overlap):
    if overlap:
        return "已衔接"
    if count == 20:
        return "疑似缺口"
    return "未满上限，未衔接"


def append_followup(root, batch, receipt, star, manual):
    now = datetime.now(timezone(timedelta(hours=8)))
    status = followup_status(receipt["count"], receipt["overlapCount"])
    if not manual and status != "疑似缺口":
        return
    folder = root / "follow-up"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now.date()}.jsonl"
    event = {key: receipt[key] for key in ("baselineBatchId", "batchId", "count", "overlapCount")}
    event.update(at=now.isoformat(), marketplace=batch["marketplace"], asin=batch["asin"],
                 star=star, mode="manual" if manual else "auto", status=status, path=batch["path"])
    # Repeating an import on the same day can recover a missing log after a crash.
    with path.open("a+", encoding="utf-8") as log:
        log.seek(0)
        if any(json.loads(line)["batchId"] == event["batchId"] for line in log if line.strip()):
            return
        log.write(json.dumps(event, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="校验 Excel 并导入评论 API")
    parser.add_argument("file", type=Path)
    parser.add_argument("--outputs", type=Path, default=Path(__file__).resolve().parents[1] / "outputs")
    parser.add_argument("--api", default=os.getenv("REVIEWS_API_URL", "http://192.168.3.36:30003"))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--naive-offset", default="+08:00", help="Excel 无时区采集时间的 UTC 偏移")
    parser.add_argument("--baseline-batch-id", type=int, help="原总查询的入库批次 ID")
    parser.add_argument("--follow-up-star", type=int, choices=range(1, 6), help="本次补查的星级")
    parser.add_argument("--manual", action="store_true", help="人工跟进，记录每次有效回执")
    parser.add_argument("--daily", action="store_true", help="每日总查询，要求带历史重叠数的回执")
    args = parser.parse_args()
    if (args.baseline_batch_id is None) != (args.follow_up_star is None):
        parser.error("补查时同时提供 --baseline-batch-id 和 --follow-up-star")
    if args.baseline_batch_id is not None and (args.baseline_batch_id <= 0 or args.daily):
        parser.error("补查需要正数基准批次，不能同时指定 --daily")
    if args.manual and args.follow_up_star is None:
        parser.error("--manual 只用于指定基准和星级的补查")
    batch = read_batch(args.file, args.outputs, args.naive_offset)
    if args.baseline_batch_id is not None:
        if any(r["star"] != args.follow_up_star for r in batch["reviews"]):
            parser.error("补查工作簿含有不符合指定星级的评论")
        batch["baselineBatchId"] = args.baseline_batch_id
    if args.check_only:
        print(json.dumps({k: batch[k] for k in ("path", "sha256", "count")}, ensure_ascii=False))
        return
    request = Request(args.api.rstrip("/") + "/api/reviews/import",
                      data=json.dumps(batch).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=60) as response:
        receipt = json.load(response)
    if (receipt.get("sha256") != batch["sha256"] or receipt.get("count") != batch["count"]
            or not isinstance(receipt.get("batchId"), int)):
        raise ValueError("入库回执与文件不匹配")
    overlap = receipt.get("overlapCount")
    if overlap is not None and (type(overlap) is not int or not 0 <= overlap <= batch["count"]):
        raise ValueError("回执的 overlapCount 无效")
    if args.daily or args.follow_up_star is not None:
        if (overlap is None or type(receipt.get("hadPriorReviews")) is not bool
                or receipt.get("baselineBatchId") != args.baseline_batch_id):
            raise ValueError("待核对：导入回执缺少有效的历史基准或重叠信息；保留工作簿")
    if args.follow_up_star is not None:
        append_followup(args.outputs, batch, receipt, args.follow_up_star, args.manual)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read(2048).decode(errors='replace')}")
    except (OSError, URLError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc))
