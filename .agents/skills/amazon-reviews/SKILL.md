---
name: amazon-reviews
description: 按 ASIN 用卖家精灵 MCP 采集亚马逊商品评论并生成校验 Excel，或将一个已有评论工作簿导入独立的内网评论 API。
---

在包含 scripts/review_workbook.py 的项目根目录运行脚本。仅执行用户指定的采集或导入步骤；要求“采集并导入”时按顺序执行。

## 采集

- ASIN 必填，站点默认 US，星级可选，排序默认 DATE_DESC，条数默认 20。显式条数应为 1–20。按当前卖家精灵 MCP 的 asin.review.list 参数契约映射实际站点、星级与排序。工具不可用或不支持指定筛选时说明情况。一次查询使用请求的上限，按实际返回数导出，不为凑数或导入再次调用。
- 在同一次响应中提取评论数组与查询元数据。保留原始正文、日期、布尔标记、规格、图片、视频。缺失字段留空，数组保持列表。不要将查询 ASIN 当作每条评论经核实的变体 ASIN。
- 从项目 scripts/review_workbook.py 调用 export_workbook(path, metadata, reviews)。reviews 使用该模块 KEYS 指定的英文键。metadata 使用“来源”（卖家精灵 MCP · asin.review.list）、sort、limit、asin、marketplace、实际星级筛选（如有）、returnedReviewCount 和 collectedAt；保留响应提供的 collectionStatus、coverageStartDate、coverageEndDate、parentAsin、retrievedAt、returnedSkuMatchedReviewCount、totalStoredReviewCount、chargedUnits、remainingUnits、requestId。缺失的供应商标识或扣次留空。优先使用上游采集时间，如无则记录本次采集时间并注明来源；新生成的本地时间带 UTC 偏移。添加“字段说明”说明空白和 JSON 数组约定。
- 每次采集用独立目录 outputs/<采集目录 ID>/，没有现成目录 ID 时生成 UUID。文件名包含 ASIN、站点、条数。保留原始文件。运行 scripts/import_reviews.py "<文件路径>" --check-only 校验，报告路径及实际条数。

## 导入

- “采集并导入”时，校验成功后将刚才传给 `--check-only` 的同一个本地 Excel 路径传给 `python scripts/import_reviews.py "<文件路径>"`。可使用绝对路径或从项目根目录起算的 `outputs/...` 路径。校验回执中的 `path` 是相对于 `outputs` 的批次记录路径。单独导入时使用用户指定或上下文中已明确的文件；只有无法确定目标文件时才询问。
- 默认直接运行导入命令。脚本按 `--api`、本地环境变量 `REVIEWS_API_URL`、内置地址 `http://192.168.3.36:30003` 的优先顺序选择服务。使用默认服务时无需询问地址或要求用户设置环境变量。
- 脚本读取两张工作表并校验条数与评论 ID，提交时省略 images、videos。成功后报告回执中的批次 ID、条数和是否重复导入。响应丢失可用同一文件重试。
