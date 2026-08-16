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

原有评测主线仍保持 **32/32 tests**；加上 SEARCH-CUP-02 P0 的 **21/21** 项，当前全仓为 **53/53**。

## Historical Failure Benchmark v0.4

历史错误基准将 89 条纵向纠错观察、18 个原始类别压缩为 12 个机制簇与 24 个 public-safe 合成案例；每簇由一个 `TRAP` 和一个匹配 `CONTROL` 构成。它不公开原始私密材料，也不把 89 条观察翻译成 89 个 `if/else`。

```bash
llm-eval \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

当前确定性基准：置信表面基线 **50%**，统一证据—约束门 **100%**，已抓住 **12/12** 个已知陷阱，逐观察规则数 **0**。全仓测试现为 **32/32**。这些数字只描述合成结构基准，不代表真实模型泛化、生产可靠性或科学 benchmark 有效性。

## Persistent Experiment Tracking v0.5

`llm-eval` 现在可以把每次运行原子写入 SQLite，记录 run ID、suite version、model/policy、prompt version、metrics、latency、token cost、git commit、UTC timestamp 与 canonical result JSON。`run_id` 不可变，重复写入会被拒绝；`--list-runs` 可回读元数据，`--log-json` 输出结构化生命周期日志。数据库属于运行证据，默认被 git 忽略，不进入公开仓库。

## Read-Only FastAPI Query Surface v0.6

`llm-eval-api --store /tmp/eval-runs.sqlite3` 提供三个只读端点：
`/healthz`、`/v1/runs` 与 `/v1/runs/{run_id}`。SQLite 以 `mode=ro`
和 `query_only` 打开；接口默认只监听 `127.0.0.1`，写方法数为 **0**，
查询前后数据库哈希保持不变。

该接口只适合本地、public-safe 实验记录查询。当前没有认证、授权、限流、
公网部署或生产可靠性声明；操作方不得把私密提示词、档案定位符或账号信息写入实验元数据。

## Docker Reproducibility（v0.7 引入）

仓库新增唯一一个受控文件 `Dockerfile`，将 Companion-Mind runtime 固定在
`c6a2128271532746a5570b99ce0ccdea4618db4e`，容器以非 root 用户运行。

```bash
docker build -t llm-evaluation-lab:0.8 .
docker run --rm llm-evaluation-lab:0.8 \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

GitHub Actions 会从 clean checkout 构建镜像、核验 `0.8.0`、复跑 24 案例历史基准、
在挂载目录中生成 SQLite 记录，并通过真实 HTTP 查询容器化 API。它证明本地容器复跑能力，
不代表已经发布 registry image、完成云部署或达到生产可靠性。

## SEARCH-CUP-02 离线公平性框架 v0.8

`ENG-SC-01-P0` 已实现四名 Fake Entrant 的封闭式离线比赛：四方读取字节一致的
Candidate Card 与 CompetitionSpec；每方拥有独立的 20 次搜索硬预算；Submission
冻结并生成 SHA-256 后，程序才允许打开合成隐藏井表，并由无模型调用的确定性 Judge
生成保留各评分维度的榜单。

```bash
llm-search-cup preflight
llm-search-cup demo --format markdown
```

P0 中没有 live provider adapter、真实搜索后端、密钥读取路径或正式比赛命令，不能触发
四模型 80 次搜索。示例公司、网址、隐藏井表与分数全部是离线合成夹具，不是真实岗位。

第三仓仍保留 concept growth、prior lock-in、world-model drift、longitudinal evolution 与 experimental timeline；failure taxonomy 只是公开接口，不取代纵向评估内核。
