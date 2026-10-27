---
title: 反向传播与梯度下降
course: 机器学习
topic: 神经网络
tags: 反向传播 梯度下降 链式法则 Adam 计算图
source: 课堂笔记 第9讲
---

## 反向传播在算什么
- 前向：按计算图算出每层输出和损失 L。
- 反向：从 L 出发，用链式法则逐层求 ∂L/∂W，把上游梯度乘本层局部导数。

```
for layer in reversed(layers):
    dZ = dA * act_grad(Z)
    dW = dZ @ A_prev.T / m
    db = mean(dZ)
    dA_prev = W.T @ dZ
```

- 梯度检查：用 (f(x+ε) - f(x-ε)) / 2ε 对比解析梯度，误差小于 1e-6 才放心。

## 梯度下降家族
- 批量 GD 稳定但慢；SGD 噪声大；mini-batch 折中，batch 常见 32/64/256。
- Momentum 累积历史梯度抑制震荡；Adam 用一阶、二阶矩自适应学习率，通常从 lr=1e-3 起试。
- 学习率太大发散、太小不收敛，先做 lr range test 再定。

## 坑
- 忘记 zero_grad 会梯度累加。
- 梯度消失或爆炸时先查初始化和归一化，再考虑梯度裁剪。