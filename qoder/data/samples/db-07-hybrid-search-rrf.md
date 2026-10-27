---
title: 混合检索与 RRF 融合排序
course: 数据库系统
topic: 检索系统
tags: 混合检索 RRF 向量检索 全文检索 结构化过滤
source: 论文摘录 + 组会讨论
---

## 为什么不能只靠一种检索
- 纯向量：同义表达召回好，但容易把「意思相近、事实不对」的段落排前面。
- 纯全文：关键词精确，但对「隔离级别」和「并发可见性」这类换说法无能为力。
- 结构化过滤只能缩小范围，不能排序。

## RRF
Reciprocal Rank Fusion 只看名次、不看分数，天然规避两路分数量纲不一致：

```
score(d) = Σ_i 1 / (k + rank_i(d)),  k = 60
```

- 常见参数 `rank_constant=60`、`rank_window_size=60`。
- 优点：实现简单、无需归一化、对某一路噪声鲁棒；缺点：丢掉了分差信息。

## seekdb 里的调用形态
`collection.hybrid_search(knn=..., query={"where_document": {"$contains": q}, "where": ...}, rank={"rrf": {...}}, n_results=k)`

- 向量一路、全文一路各自召回，引擎内做 RRF，再按元数据 where 过滤。
- 若引擎版本不支持 hybrid_search，就降级为两路分别查、应用层合并，并在响应 `debug.degraded` 里标记。