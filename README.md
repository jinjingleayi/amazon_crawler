# Amazon Crawler (Playwright)

功能概述：
- 按关键词在 Amazon 搜索，获取搜索结果前 3 个产品详情页链接
- 进入评论页，按星级（1~5 星）筛选并抓取评论，至少翻页一次
- 通过可视化登录获取 Cookies（Playwright storage state），实现持久化登录

## 环境准备

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## 首次登录（保存 Cookies）

```bash
python main.py --login
```
- 会打开 Chromium 窗口，请在窗口中手动完成登录（包含验证码/MFA）。
- 登录成功后回到终端按 ENTER，将会保存登录会话到 `storage_state.json`。
- 注意：`storage_state.json` 已在 `.gitignore` 忽略，不会被提交。

## 运行示例

1) 交互式搜索（获取前 3 个产品链接），选择星级和翻页数
```bash
python main.py --pages 2 --limit 3
# 按提示输入关键词（如 smart watch），再输入星级（1-5 或 "5星"）
```

2) 直接用产品详情页/评论页链接
```bash
# 单个产品，1 页，4 星
python main.py --urls "https://www.amazon.com/product-reviews/<ASIN>?filterByStar=four_star&reviewerType=all_reviews" --pages 1 --limit 1
# 或：
python main.py --urls "https://www.amazon.com/dp/<ASIN>" --pages 2 --limit 1
# 按提示输入星级 1~5
```

输出：
- 结果写入 `output/` 目录（CSV 与 JSON）

## 三项功能如何实现

1) 支持通过关键词在亚马逊上搜索产品，并获取搜索结果中前 3 个产品的详情页链接。
   - 入口：`amazon_search.py` 中的 `search_top_products(keyword, limit=3, ...)`。
   - 方式：打开 `https://www.amazon.com/s?k=关键词`，选择前若干个带 `/dp/` 的详情页链接，返回前 3 个。

2) 支持按照评论星级筛选，抓取每个产品的用户评论（需至少分页抓取一次），包括评论内容、评论星级、评论时间、评论者昵称等。
   - 入口：`amazon_reviews.py` 中的 `scrape_reviews_for_product(product_url, star, max_pages, ...)`。
   - 方式：
     - 从商品详情页进入“所有评论”页，或按 ASIN 构造评论页链接。
     - 优先尝试点击页面上的星级过滤；若不可用，则在 URL 中附带 `filterByStar`、`reviewerType`、`pageNumber` 参数加载。
     - 解析 DOM 中的评论块（`data-hook="review"`、`review-body`、`review-date`、`a-profile-name` 等），并加入针对不同页面结构的兜底选择器。
     - 当 DOM 抽取不到时，调用 Amazon 的评论异步接口（reviews-render ajax）获取 HTML 片段并解析，确保能提取：
       - 评论内容（review_content）
       - 评论星级文本（review_rating_text）
       - 评论时间（review_date）
       - 评论者昵称（reviewer）

3) 使用自动化工具登录账户获取 Cookies，实现爬虫持久化登录。
   - 入口：`amazon_login.py` 中的 `interactive_login(...)`。
   - 方式：
     - 启动 Playwright（Chromium），打开 Amazon 登录页，提示用户在弹出的浏览器窗口中手动完成登录。
     - 登录完成后按 ENTER，保存 `storage_state.json`（包含 Cookies 等登录状态），后续请求带上该状态，实现免登录访问。
   - 安全：`storage_state.json` 已加入 `.gitignore`，不会被提交到 Git 仓库。

## 注意事项
- 建议在可视化模式（不加 `--headless`）下运行，便于处理弹窗、地区选择、验证码等。
- 请合理控制抓取频率与页数，遵循目标网站的服务条款与政策。
- 不要在仓库中提交任何与个人账号相关的敏感信息（Cookies、密码等）。
