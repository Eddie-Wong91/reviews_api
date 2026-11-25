# Amazon 评论采集与导入

采集在本地使用卖家精灵 MCP；项目级 Skill 位于 `.agents/skills/amazon-reviews/SKILL.md`。采集与导入可分别执行。ASIN 必填，默认美国站、日期降序、最多 20 条。原始 Excel 保存在 `outputs/<采集目录 ID>/`，请保留该目录用于核验和重试。

## 本地导入

安装 Python 3.11+，在项目根目录执行（示例中的路径替换为实际工作簿）。

```powershell
python -m pip install -r scripts/requirements.txt
python scripts/import_reviews.py "outputs/<采集目录 ID>/评论.xlsx" --check-only
python scripts/import_reviews.py "outputs/<采集目录 ID>/评论.xlsx" --api http://192.168.3.36:30003
```

Excel 使用“评论明细”和“查询与扣次”两张工作表。时间戳带偏移时使用原偏移；历史工作簿的无时区采集时间默认按 UTC+08:00 解读，可用 `--naive-offset=+00:00` 等覆盖。入库跳过图片和视频。一个事务提交评论及批次，按目录 ID 与文件 SHA-256 识别重试。批次表记录相对路径、来源、上游请求 ID、ASIN、站点、条数和时间。商品评论按站点、查询 ASIN 和评论 ID 去重，首次插入，后续导入的评论字段发生变化时直接覆盖主表。仅采集时间变化时跳过更新。同一批次重试仍返回原回执。响应中的 count 表示确认的文件行数，包含已存在的评论。

## 部署独立服务

将 `reviews_api/` 同步到服务器（例如 `/opt/amazon_reviews_api/`），保留服务器原有的 .env。确认内网端口 30003 可用，且容器可达 PostgreSQL。首次部署时用管理账号在 amazon_db 依次执行 sql/001_init_reviews.sql 和 sql/002_review_overlap.sql，再为运行账号授权。已有 001 的部署按下方升级步骤操作。首次创建角色的示例：

```sql
CREATE ROLE amazon_reviews_api LOGIN;
\password amazon_reviews_api
GRANT CONNECT ON DATABASE amazon_db TO amazon_reviews_api;
GRANT USAGE ON SCHEMA amazon_reviews TO amazon_reviews_api;
GRANT SELECT, INSERT ON amazon_reviews.import_batches TO amazon_reviews_api;
GRANT SELECT, INSERT, UPDATE ON amazon_reviews.reviews TO amazon_reviews_api;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA amazon_reviews TO amazon_reviews_api;
```

在部署目录复制 `.env.example` 为 `.env`，填写实际 PGHOST、PGUSER、PGPASSWORD 和内网监听地址。限制该文件权限；免 Token 的接口仅向受信任内网客户端开放，避免配置公网代理转发到此服务。

```sh
docker compose up -d --build --no-deps reviews-api
curl --fail http://192.168.3.36:30003/health/ready
```

SQL 迁移由管理员执行。后续发布评论服务时在这个独立的 Compose 项目下更新镜像。

## 已部署实例升级与验证

先同步新版 reviews_api 目录，暂停导入任务。在部署目录运行以下命令。psql 使用管理员的连接设置（含实际主机及用户）；002 仅执行一次。迁移事务成功后再启动新版 API。原有表级权限已覆盖新增字段。

```sh
cd /opt/amazon_reviews_api
docker compose stop reviews-api
psql -X -v ON_ERROR_STOP=1 -d amazon_db -f sql/002_review_overlap.sql
docker compose up -d --build --no-deps reviews-api
docker compose ps reviews-api
curl --fail http://192.168.3.36:30003/health/ready
```

如管理员通过 PostgreSQL 容器内的 psql 连接，将 SQL 文件通过标准输入传给该容器的 psql，并指定目标库 amazon_db。健康检查应返回 `{"ready":true}`；失败时用 `docker compose logs --tail=100 reviews-api` 查看原因，排除后再恢复采集。切换期间保持旧版写入暂停，以免新增评论被误认为迁移前库存。

## 每日采集与人工跟进

每日总查询的工作簿导入时加 `--daily`。回执里 hadPriorReviews 表示基准开始前有无此站点、此 ASIN 的历史评论；overlapCount 是文件中与这份历史匹配的 ID 数。首次建档或未满 20 条即结束。已有历史、满 20 条且零重叠时，才分星补查。衔接只说明命中历史 ID；延迟收录和同日排序仍可能造成遗漏。

补查时把总查询返回的 batchId 作为固定基准。例如导入五星补查文件：

```powershell
python scripts/import_reviews.py "outputs/<新的采集目录>/评论.xlsx" --baseline-batch-id 120 --follow-up-star 5
```

人工跟进时额外加 `--manual`。疑似缺口与人工结果按北京时间追加到 outputs/follow-up/YYYY-MM-DD.jsonl，同一缺口由站点、ASIN、星级和原总查询批次共同定位。每次新查询用新的工作簿；同一文件重试用原参数。迁移前已存在的评论参与新任务的历史核对，旧批次重放时历史统计为空。
