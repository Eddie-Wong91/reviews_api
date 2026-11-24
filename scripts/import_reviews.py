import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from review_workbook import read_batch


def main():
    parser = argparse.ArgumentParser(description="校验 Excel 并导入评论 API")
    parser.add_argument("file", type=Path)
    parser.add_argument("--outputs", type=Path, default=Path(__file__).resolve().parents[1] / "outputs")
    parser.add_argument("--api", default=os.getenv("REVIEWS_API_URL", "http://192.168.3.36:30003"))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--naive-offset", default="+08:00", help="Excel 无时区采集时间的 UTC 偏移")
    args = parser.parse_args()
    batch = read_batch(args.file, args.outputs, args.naive_offset)
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
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        raise SystemExit(f"HTTP {exc.code}: {exc.read(2048).decode(errors='replace')}")
    except (OSError, URLError, ValueError, KeyError) as exc:
        raise SystemExit(str(exc))
