# LLM Evaluation Lab｜A2 / Measure the system

**面向失败机制、改进验证、独立系统 Gate、回归测试与长期证据的可运行评测实验室。**

Portfolio Status：**CURRENT ARTIFACT** · Evidence Level：**E3——可复现的 public-safe 评测**

LLM Evaluation Lab 不再把自己描述成“第三仓库概念稿”，也不是 Companion-Mind 的附属 QA 仓。它负责把真实或历史 AI 系统失败转换成：可复现 case、明确 rubric/oracle、baseline、可证伪 mitigation、独立验证与 regression evidence。

配套的 [Companion-Mind](https://github.com/aerenkolstein-code/Companion-Mind) 是 A1 / implementation 仓：

> **A1 builds the system. A2 measures whether it actually improves.**

## 当前最近评测 Gate

当前产品关联的第一硬 Gate 是 **A019 / Gate E1｜Durable Journal black-box evaluation**，不是旧叙事里的 Day 1 / 7 / 30 / 90 Persona 主线。

已发布的 A2 Wave 1 Stage Plan 把以下八个维度定义为独立黑盒评测目标：

```text
Durability
Ordering
Dedupe
Crash Recovery
Restart Recovery
Correction
Secret Exclusion
UNKNOWN Semantics
```

E1 是 all-of gate：zero-tolerance invariant 不能用平均分冲掉。当前 Stage Plan 已发布，但实现与 E1 实跑仍需独立授权，并等待 A1-D candidate 与 sanctioned black-box seam。

E1 之后，评测对象随系统主线继续生长：

```text
Journal / E1
→ Context Engine / Owned Home
→ Retrieval / Authority Router
→ Model Gateway / model-switch continuity
→ W1 operational independence
→ Living Lab longitudinal reliability
→ W2 evidence readiness
```

这条路线不预先选定商业伴侣产品；只有未来真实长期使用证据支持并重新立项时，才会出现商业评测 profile。

## 四条长期主线

1. **Failure Mechanism Lab**：failure taxonomy、mechanism clustering、minimal pair、TRAP/CONTROL、baseline、mitigation、falsification、regression。
2. **A2 Independent System Gates**：独立验证 A1/Runtime 承诺，不复制 A1 schema，不让系统自己给自己发证书。
3. **RAW Harvest + Historical / Era Benchmarks**：私有长期 RAW/L0 作为 evidence mine，提炼 public-safe mechanism、synthetic replay、rubric 与跨代比较；原始私人材料不进公开仓。
4. **Longitudinal Cognitive / Persona Research**：Concept Growth、Reasoning Trajectory、World Model Evolution、Personality/Relationship Continuity、Prior Lock-in、Attractor Stability、Replay 等长期问题，在证据和 protocol 足够成熟时再正式 benchmark 化。

当前路线详见：
- `docs/current-roadmap.md`
- `docs/methodology.md`
- `docs/method-lineage.md`

## First Closed Loop

首个闭环 `EVAL-CASE-001` 测试 Premature Parent Closure：一个局部子任务完成，另一个必要子任务仍未闭环，系统却把父目标写成完成。

五个确定性变体的实测结果：

| 策略 | 准确率 | 过早关闭率 | 回归失败数 |
|---|---:|---:|---:|
| 朴素基线 | 20% | 100% | 4 |
| Companion-Mind Closure Guard | 100% | 0% | 0 |

这不是通用模型性能声明，而是第一个能被陌生人复跑的 Case → Failure → Baseline → Mitigation → Guard → Regression 闭环。

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

`llm-eval` 校验并输出完整的 `mitigation-spec/v1`，再用它实例化 Companion-Mind 的真实 `ClosureGuard`。报告记录 runtime 实际加载的 mitigation ID、safeguard ID、schema version 与 canonical SHA-256 fingerprint，从而证明“评测里写的 mitigation”与“运行时实际执行的 mitigation”一致。

当前 **32/32 tests** 覆盖 Case/Spec 同步、非法规范、状态集合冲突、真实 runtime 回归、checked result、历史机制簇、最小对照、隐私定位符、双套 suite 的 SQLite 持久化、重复 run 防覆盖、结构化日志、只读 API、双格式报告、CLI 原子输出与退出码契约。

## Historical Failure Benchmark v0.4

历史错误基准将 89 条纵向纠错观察、18 个原始类别压缩为 12 个机制簇与 24 个 public-safe 合成案例；每簇由一个 `TRAP` 和一个匹配 `CONTROL` 构成。它不公开原始私密材料，也不把 89 条观察翻译成 89 个 `if/else`。

```bash
llm-eval \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

当前确定性基准：置信表面基线 **50%**，统一证据—约束门 **100%**，已抓住 **12/12** 个已知陷阱，逐观察规则数 **0**。这些数字只描述合成结构基准，不代表真实模型泛化、生产可靠性或科学 benchmark 有效性。

## 方法论主链

长期方法现在冻结为：

```text
Observed Failure / Friction
→ Phenomenon Classification
→ Mechanism Hypothesis / Cluster
→ Reproducible Case
→ Rubric / Oracle
→ Baseline
→ Mitigation Hypothesis
→ Independent Verification / Falsification
→ Regression
→ Cross-Method Comparison
→ Review
→ Best-Known Solution
```

原则是：先复现，再修；先区分现象和机制，再归因；Falsification 与 PASS 同样重要；Regression 是 mitigation 的一部分；`BLOCKED / NOT EVALUABLE` 不能伪装成 GREEN。

而且“AI failure”不再自动等于“模型错了”。候选层包括：model、context assembly、retrieval/authority routing、tool/provider adapter、durable state/journal、persona/relationship continuity、model switching、crash/restart 等。

## RAW Harvest 与历史 benchmark

历史 RAW 具有两种不同的评测价值：

- **Historical Observed Baseline**：按后来冻结的 rubric 回评旧模型当年真实输出；保留其历史环境无法完全复原的限制。
- **Frozen Replay Benchmark**：把必要 task、visible context、约束、证据和 oracle 脱敏冻结，让后来的模型或 Runtime 在同一个可复跑输入包上比较。

因此：

> **Archive Complete ≠ Eval Harvest Complete。**

原矿恢复和归档只是第一层完成。真正 Eval Harvest 还要经过 candidate → mechanism → anonymization/synthetic abstraction → rubric/oracle → baseline → mitigation → falsification → regression → longitudinal comparison。

私人 RAW/L0 是 evidence mine，不是公开训练集。公开仓只接受脱敏/合成 case、机制、rubric、protocol、aggregate metric、mitigation spec、regression evidence 和 public-safe trace。

## Persistent Experiment Tracking v0.5

`llm-eval` 可以把每次运行原子写入 SQLite，记录 run ID、suite version、model/policy、prompt version、metrics、latency、token cost、git commit、UTC timestamp 与 canonical result JSON。`run_id` 不可变，重复写入会被拒绝；`--list-runs` 可回读元数据，`--log-json` 输出结构化生命周期日志。数据库属于运行证据，默认被 git 忽略，不进入公开仓库。

## Read-Only FastAPI Query Surface v0.6

`llm-eval-api --store /tmp/eval-runs.sqlite3` 提供三个只读端点：`/healthz`、`/v1/runs` 与 `/v1/runs/{run_id}`。SQLite 以 `mode=ro` 和 `query_only` 打开；接口默认只监听 `127.0.0.1`，写方法数为 **0**，查询前后数据库哈希保持不变。

该接口只适合本地、public-safe 实验记录查询。当前没有认证、授权、限流、公网部署或生产可靠性声明。

## Docker Reproducibility v0.7

仓库包含一个受控 `Dockerfile`，将 Companion-Mind runtime 固定在 `c6a2128271532746a5570b99ce0ccdea4618db4e`，容器以非 root 用户运行。

```bash
docker build -t llm-evaluation-lab:0.7 .
docker run --rm llm-evaluation-lab:0.7 \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

GitHub Actions 会从 clean checkout 构建镜像、核验 `0.7.0`、复跑 24 案例历史基准、在挂载目录中生成 SQLite 记录，并通过真实 HTTP 查询容器化 API。它证明本地容器复跑能力，不代表已发布 registry image、完成云部署或达到生产可靠性。

## Claims Boundary

当前**已经实现**的是：First Closed Loop、Historical Failure Benchmark、MitigationSpec integration、SQLite immutable experiment tracking、结构化日志、只读 API、Docker reproducibility 与当前 32/32 tests。

当前**尚未宣称**的是：

```text
scientific benchmark validity
corpus representativeness
broad model generalization
live-model statistical significance
production / enterprise eval platform
人格 / 意识的客观 ground truth
private RAW 可公开训练
一个总分代表长期 AI 质量
```

第三仓时期留下的 concept growth、prior lock-in、world-model drift、experimental timeline 等问题继续保留为长期 research program；它们不再冒充当前首期施工命令。
