# LLM Evaluation Lab

> 中文说明：SEARCH-CUP-02 当前进入 **v2.2 搜索评测架构对账阶段**。现有 P0/P1/P2 工程资产继续保留，但在继续 P3-P5 前，需要把 Search Architecture、裸模型 Search Execution、Result Judgment 与 Retriever / Search Stack 能力分开测。
>
> 当前架构文档：[`docs/search-cup-v2.2-architecture-reconciliation.md`](docs/search-cup-v2.2-architecture-reconciliation.md)
>
> 核心边界：四模型主杯赛使用同一中性/透明检索器进行“裸模型”比较；GLM Search / Search Agent 作为独立搜索系统挑战者另赛；Live Web 与 Frozen Corpus 分轨；Judgment 可在统一、盲化候选集上单测。v2.2 Protocol Gate 批准前，不进入 P3-P5，不执行正式付费/live 比赛。

---

本仓库用于可复现的 LLM 评测、失败机制回归、缓解方案实验、不可变证据记录以及搜索/智能体评测。英文 README 保留完整可复现实验说明与当前 Search Cup P0/P1/P2 证据。
