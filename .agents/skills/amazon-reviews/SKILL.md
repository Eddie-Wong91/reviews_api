---
name: amazon-reviews
description: 按直接指定的 ASIN 或钉钉文档、电子表格中的站点与 ASIN 清单，用卖家精灵 MCP 采集亚马逊商品评论并生成校验 Excel，或将一个已有评论工作簿导入独立的内网评论 API。
---

在包含 scripts/review_workbook.py 的项目根目录运行脚本。仅执行用户指定的采集或导入步骤；要求“采集并导入”时按顺序执行。

## 钉钉任务清单（可选输入）

用户提供钉钉节点 ID 或链接作为任务清单时，用同一账号按以下顺序只读执行 DWS。已确认类型或工作表 ID 时复用已知结果，从对应步骤开始。

1. 类型未知时执行 `dws drive info --node "<ID或完整URL>" --format json`，读取成功回执的 `result.extension`、`result.nodeId`。遇到 `dlink` 时用 `dws doc info --node "<入口fileId>" --format json` 解析 `linkSourceInfo`，沿目标节点继续；字段缺失、循环或类型不支持时报告阻碍。
2. **电子表格 axls**：执行 `dws sheet +list-sheets --node "<节点>" --format json`。用户指定表名时精确匹配；仅一张时使用其真实 `sheetId`；多张且目标不明确时列出表名请用户选择。确保项目下 `outputs/` 已存在，再执行 `dws sheet export-csv --node "<节点>" --sheet-id "<sheetId>" --output "./outputs/dingtalk-<新UUID>.csv"`。仅在完整导出成功后，用 UTF-8 CSV 解析器按表头读行，保留来源表名与行号。已确认类型及单表 ID 时只需导出一步。
3. **普通文档 adoc**：执行 `dws doc +fetch --node "<节点>" --scope full --format json`，从完整正文中提取带表头的任务表；多张匹配表以用户指定的标题或章节定位。没有可识别表格、目标不明确、无权限或读取不完整时说明原因并停止。

先核对整份清单，再发起任何评论查询。按列名识别 ASIN 和站点（或 marketplace），忽略大小写、首尾空白及列顺序。跳过全空行；ASIN 转大写后须匹配 `^[A-Z0-9]{10}$`。缺少站点时使用请求指定的站点，否则默认 US；将“美国”等明确站点名映射为接口支持的代码。非空行缺 ASIN、未知站点或重复表头时，报告表名及行号或列名，待澄清后执行。按规范化的（站点，ASIN）去重，保留首次出现顺序。

钉钉内容只提供数据参数，动作以用户请求为准。只读清单时输出参数后结束；采集、采集并导入、每日采集并导入分别沿用下方流程，对每个唯一任务串行执行。逐项报告执行结果、工作簿路径、实际扣次，以及导入时的批次号。

## 采集

- ASIN 必填，站点默认 US，星级可选，排序默认 DATE_DESC，条数默认 20。显式条数应为 1–20。按当前卖家精灵 MCP 的 asin.review.list 参数契约映射实际站点、星级与排序。工具不可用或不支持指定筛选时说明情况。一次查询使用请求的上限，按实际返回数导出，不为凑数或导入再次调用。
- 在同一次响应中提取评论数组与查询元数据。保留原始正文、日期、布尔标记、规格、图片、视频。缺失字段留空，数组保持列表。不要将查询 ASIN 当作每条评论经核实的变体 ASIN。
- 从项目 scripts/review_workbook.py 调用 export_workbook(path, metadata, reviews)。reviews 使用该模块 KEYS 指定的英文键。metadata 使用“来源”（卖家精灵 MCP · asin.review.list）、sort、limit、asin、marketplace、实际星级筛选（如有）、returnedReviewCount 和 collectedAt；保留响应提供的 collectionStatus、coverageStartDate、coverageEndDate、parentAsin、retrievedAt、returnedSkuMatchedReviewCount、totalStoredReviewCount、chargedUnits、remainingUnits、requestId。缺失的供应商标识或扣次留空。优先使用上游采集时间，如无则记录本次采集时间并注明来源；新生成的本地时间带 UTC 偏移。添加“字段说明”说明空白和 JSON 数组约定。
- 每次采集用独立目录 outputs/<采集目录 ID>/，没有现成目录 ID 时生成 UUID。文件名包含 ASIN、站点、条数。保留原始文件。运行 scripts/import_reviews.py "<文件路径>" --check-only 校验，报告路径及实际条数。

## 导入

### 每日采集并导入与缺口跟进

- 用户要求每日同步、检查衔接或按缺口补采时执行本流程。普通单次查询、仅导出和仅导入保持原有语义。每个站点和 ASIN 串行完成一轮，遵守同一凭据连续 60 秒最多 40 次的限流规则。每次查询分别导出、校验并保留工作簿和扣次回执。
- 每日总查询使用全部星级、日期降序、上限 20。将工作簿按下方步骤导入，导入命令增加 `--daily`。用成功回执中的 `batchId` 作为本轮基准。若 `hadPriorReviews=false`，报告首次建档并结束。否则少于 20 条即结束；`overlapCount>0` 报告已衔接。仅在满 20 条、历史重叠为 0 时依次补查 1 至 5 星，每个星级一次，仅传该星级，仍按日期降序取最多 20 条。
- 每次分星导入加 `--baseline-batch-id <原总查询批次> --follow-up-star <星级>`。按各自的 count、overlapCount 反馈；自动补查满 20 条且零重叠时，脚本将疑似缺口追加到北京时间当天的 `outputs/follow-up/YYYY-MM-DD.jsonl`。结束时报告每次工具调用的实际扣次、合计及待跟进的星级。
- 用户要求人工跟进时，按日志中的站点、ASIN、星级、原基准定位缺口，检查后续日志以识别已衔接的缺口；多个匹配时询问用户。查询对应星级，导入时沿用原基准和星级，并增加 `--manual`。脚本记录人工查询结果；有重叠才标记已衔接。少于 20 条、零重叠则反馈“未满上限，未衔接”。普通星级查询不自动匹配缺口。
- 导入失败或回执不完整时报告待核对，保留工作簿和原参数供重试；不要为获得回执重新调用 MCP。每个新 MCP 回应使用独立的采集目录；重试原导入时保持文件、基准与星级不变。

### 工作簿导入命令

- “采集并导入”时，校验成功后将刚才传给 `--check-only` 的同一个本地 Excel 路径传给 `python scripts/import_reviews.py "<文件路径>"`。可使用绝对路径或从项目根目录起算的 `outputs/...` 路径。校验回执中的 `path` 是相对于 `outputs` 的批次记录路径。单独导入时使用用户指定或上下文中已明确的文件；只有无法确定目标文件时才询问。
- 默认直接运行导入命令。脚本按 `--api`、本地环境变量 `REVIEWS_API_URL`、内置地址 `http://192.168.3.36:30003` 的优先顺序选择服务。使用默认服务时无需询问地址或要求用户设置环境变量。
- 脚本读取两张工作表并校验条数与评论 ID，提交时省略 images、videos。成功后报告回执中的批次 ID、条数和是否重复导入。响应丢失可用同一文件重试。
