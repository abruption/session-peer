# 下载指标

README 中的 PyPI 月度下载徽章由 [Pepy](https://pepy.tech/pepy-api) 直接提供。点击它可以打开 [session-peer 统计数据](https://pepy.tech/projects/session-peer)。公开月度徽章统计最近 30 天，而不是日历月或实时计数器。Pepy 的 API 文档说明公开徽章端点不需要 API 密钥，没有速率限制，且缓存 12 小时。GitHub 图像缓存可能会进一步延迟可见的更新；徽章仍然是一项外部依赖。

月度：`https://api.pepy.tech/badge/session-peer/month`。
周度：`https://api.pepy.tech/badge/session-peer/week`（最近 7 天）。

## 解读

- 这些是 Pepy 聚合数据。公开徽章文档并未确立与 PyPI Stats 相同的镜像/CI 过滤；请勿混淆这两个提供商或声称排除了 CI 流量。有关下载衡量的限制，请参阅 [PyPA 指南](https://packaging.python.org/en/latest/guides/analyzing-pypi-package-downloads/)。
- 这些计数涵盖 `session-peer` PyPI 软件包，不包括旧版 `cc-peer`、GitHub 克隆、原始脚本安装或所有软件包来源。
- 徽章不可用、受到速率限制或未知并不代表零下载。请访问来源链接了解背景；README 不会替换为硬编码的计数。

该徽章与现有的 README 徽章一样是远程图像。它不引入 CLI 遥测，也不引入仓库拥有的收集器、数据库或定时工作流。版本保持不变；文档更新不需要发布新版本。

## 独立的落地页实现

本体（ontology）会话拥有落地页。对其单独标记的最近 7 天和最近 30 天 PyPI 指标使用相同的 Pepy 公开周度与月度徽章，保持来源和提供商错误状态清晰。这避免了 JSON API 密钥或单独的收集器。切勿在公开代码中暴露 Pepy JSON API 密钥；JSON API 访问具有与公开徽章不同的身份验证、方案和速率限制条件。现有的网站分析保持不变；此项工作未添加 CLI 或访客事件遥测。

## 提供商变更验证 (2026-09-18)

最初的 Shields.io 徽章使用的是 PyPI Stats。直接访问 PyPI Stats 返回了 HTTP429，且原始徽章先前显示了上游速率限制错误；额外的图像缓存参数并未消除上游依赖。使用 curl，Pepy 的两个公开端点均返回了 HTTP200 以及 session-peer 的 SVG 数字徽章（观察时的四舍五入标签为月度 `2k` 和周度 `1k`）。这些四舍五入的观察结果并未硬编码到 README 中，也不确立确切的整数计数或长期服务可用性。最初的 Python urllib 请求返回了 403，因此 curl 结果绝不能推广到所有客户端。浏览器和 GitHub 图像代理的可达性仍属于独立的检查。

## GitHub 后续工作

[GitHub 发布版本 API](https://docs.github.com/en/rest/releases/releases) 公开了上传发布资产的累计 `download_count`。周度/月度值需要带日期的快照以及按稳定资产 ID 计算的差值。缺失基线、已移除或替换的资产以及计数器减少需要显式的未知或连续性状态；无法从单次累计读取中恢复历史周期数据。将 GitHub 资产下载与 PyPI 区分开来，不要将其标记为克隆或原始独立安装程序流量。在首个 README 更改中未实现快照自动化。
