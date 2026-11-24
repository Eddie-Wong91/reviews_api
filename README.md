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

将 `reviews_api/` 同步到服务器（例如 `/opt/amazon_reviews_api/`）。先确认内网端口 30003 可用，并确认 API 容器可达现有 PostgreSQL。首次部署时，用管理账号连接目标数据库 `amazon_db`，执行 `sql/001_init_reviews.sql`。已完成初始化和授权的部署可直接更新服务。为运行账号设置密码；例如在管理员 psql 会话中创建专用角色并授权（已有角色可跳过创建）。

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
