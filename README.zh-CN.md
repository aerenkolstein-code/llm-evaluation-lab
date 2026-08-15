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

## Executable Integration v0.3

```bash
python -m pip install -e ../Companion-Mind
python -m pip install -e .
llm-eval \
  --cases cases/anonymized/premature-parent-closure.md \
  --emit-mitigation /tmp/mitigation.json \
  --output /tmp/evaluation.json
companion-mind validate-mitigation --mitigation-spec /tmp/mitigation.json
```

`llm-eval` 现在负责校验并输出完整的 `mitigation-spec/v1`，再用它实例化 Companion-Mind 的真实 `ClosureGuard`。报告同时记录 runtime 实际加载的 mitigation ID、safeguard ID、schema version 与 canonical SHA-256 fingerprint，从而证明“写入评测报告的配置”与“运行时真正执行的配置”一致。

当前 **15/15 tests** 覆盖 Case/Spec 同步、非法规范、状态集合冲突、真实 runtime 回归、checked result、双格式报告、CLI 原子输出与退出码契约。

第三仓仍保留 concept growth、prior lock-in、world-model drift、longitudinal evolution 与 experimental timeline；failure taxonomy 只是公开接口，不取代纵向评估内核。
