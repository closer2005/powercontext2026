---
title: 注意力机制与 Transformer
course: 机器学习
topic: 序列建模
tags: 注意力机制 Transformer 自注意力 多头 位置编码
source: 论文 Attention Is All You Need + 网课 CS224n Lecture 8
---

## 注意力公式

```
Attention(Q, K, V) = softmax(QKᵀ / √d_k) V
```

- Q 查询、K 键、V 值都是输入的线性变换。
- 除以 √d_k 是因为点积方差随维度增大，不缩放会让 softmax 进入饱和区、梯度很小。
- 多头注意力把 d_model 切成 h 份并行算再拼接，让不同头关注不同的子空间。

## Transformer 结构
- 编码器层 = 多头自注意力 + 前馈网络，每个子层后接残差和 LayerNorm。
- 解码器多一层 cross-attention；训练时用 mask 防止看到未来 token。
- 位置编码补回顺序信息（正弦式或可学习），因为自注意力本身对顺序不敏感。
- 复杂度 O(n²·d)，长文本要用稀疏注意力或分块。

## 和 RNN 的对比
RNN 逐步传递隐状态，长距离依赖容易梯度消失；注意力任意两位置路径长度为 1，并行度也更高。这解释了为什么现在大模型基本都是 Transformer 架构。