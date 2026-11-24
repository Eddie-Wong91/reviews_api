import json
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HEADERS = (
    "日期 / date", "星级 / star", "标题 / title", "评论原文 / content",
    "作者 / author", "已验证购买 / purchased", "Vine 评论 / vine", "有用票数 / helpful",
    "购买规格 / skus", "评论 ID / reviewId", "图片 / images", "视频 / videos",
)
KEYS = tuple(header.split(" / ")[1] for header in HEADERS)
DETAIL, META = "评论明细", "查询与扣次"


def write_cell(sheet, row, column, value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"  # Literal review text, including titles beginning with "=".


def export_workbook(path, metadata, reviews):
    if metadata["returnedReviewCount"] != len(reviews) or len(reviews) > 20:
        raise ValueError("返回条数与评论明细不符，或超过 20 条")
    book = Workbook()
    detail = book.active
    detail.title = DETAIL
    detail.append(HEADERS)
    for row, review in enumerate(reviews, 2):
        for column, key in enumerate(KEYS, 1):
            write_cell(detail, row, column, review.get(key))
    meta = book.create_sheet(META)
    meta.append(("字段", "值"))
    for row, (key, value) in enumerate(metadata.items(), 2):
        write_cell(meta, row, 1, key)
        write_cell(meta, row, 2, value)
    for sheet, widths in ((detail, [15, 13, 44, 90, 24, 23, 18, 19, 40, 25, 40, 40]),
                          (meta, [34, 76])):
        sheet.freeze_panes = "A2"
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(column)].width = width
            sheet.cell(1, column).font = Font(bold=True)
    detail.auto_filter.ref = detail.dimensions
    buffer = BytesIO()
    book.save(buffer)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(buffer.getvalue())


def read_batch(path, root, naive_offset):
    path = path.resolve()
    relative = path.relative_to(root.resolve())
    if len(relative.parts) != 2 or relative.suffix.lower() != ".xlsx":
        raise ValueError("文件应在 outputs/<采集目录>/ 下")
    data = path.read_bytes()
    book = load_workbook(BytesIO(data), read_only=True)
    try:
        meta_rows = iter(book[META].values)
        if tuple(next(meta_rows))[:2] != ("字段", "值"):
            raise ValueError("查询与扣次缺少字段和值表头")
        meta = {row[0]: row[1] for row in meta_rows if row[0]}
        rows = iter(book[DETAIL].values)
        headers = list(next(rows))
        if any(headers.count(h) != 1 for h in HEADERS):
            raise ValueError("评论明细列名缺失或重复")
        columns = [(key, headers.index(header)) for key, header in zip(KEYS, HEADERS)
                   if key not in {"images", "videos"}]
        reviews = []
        for values in rows:
            if all(v is None for v in values):
                continue
            item = {key: values[index] for key, index in columns}
            if isinstance(item["date"], datetime):
                item["date"] = item["date"].date()
            if isinstance(item["date"], date):
                item["date"] = item["date"].isoformat()
            if item["skus"] is not None:
                item["skus"] = json.loads(item["skus"])
                if not isinstance(item["skus"], list):
                    raise ValueError("skus 应为 JSON 数组")
            reviews.append(item)
    finally:
        book.close()
    ids = [item["reviewId"] for item in reviews]
    if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("评论 ID 为空或重复")
    if len(ids) > 20 or len(ids) != int(meta["returnedReviewCount"]):
        raise ValueError("评论条数不符或超过 20 条")
    observed = datetime.fromisoformat(str(meta["collectedAt"]))
    if observed.tzinfo is None:
        observed = datetime.fromisoformat(observed.isoformat() + naive_offset)
    return dict(path=relative.as_posix(), sha256=sha256(data).hexdigest(), source=meta["来源"],
                marketplace=meta["marketplace"], asin=meta["asin"], requestId=meta.get("requestId"),
                collectedAt=observed.isoformat(), count=len(ids), reviews=reviews)
