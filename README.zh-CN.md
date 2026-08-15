# LLM Evaluation Lab｜第三仓库公开形态

**面向错误机制、纵向变化、改进验证与回归测试的可运行评测架。**

Portfolio Status：**CURRENT ARTIFACT** · Evidence Level：**E3——可复现的 public-safe 评测**

首个闭环 `EVAL-CASE-001` 测试 Premature Parent Closure：一个局部子任务完成，另一个必要子任务仍未闭环，系统却把父目标写成完成。

五个确定性变体的实测结果：

| 策略 | 准确率 | 过早关闭率 | 回归失败数 |
|---|---:|---:|---:|
| 朴素基线 | 20% | 100% | 4 |
| Companion-Mind Closure Guard | 100% | 0% | 0 |

这不是通用模型性能声明，而是第一个能被陌生人复跑的 Case → Failure → Metric → Mitigation → Guard → Regression 闭环。

## CLI 纵切

```bash
python -m pip install -e ../Companion-Mind
python -m pip install -e .
llm-eval --cases cases/anonymized/premature-parent-closure.md
llm-eval --format markdown --output evaluation-report.md
```

`llm-eval` 依次完成 Case 加载与校验、基线/处理组执行、逐例评分、指标计算、回归门禁以及 JSON/Markdown 报告输出。回归失败返回退出码 `1`，输入或依赖错误返回 `2`。当前 11 项测试覆盖 fixture 同步、非法输入、实测指标、checked result、双格式报告、CLI 文件输出与退出码契约。

第三仓仍保留 concept growth、prior lock-in、world-model drift、longitudinal evolution 与 experimental timeline；failure taxonomy 只是公开接口，不取代纵向评估内核。
