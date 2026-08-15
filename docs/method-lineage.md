# Method lineage

```text
Raw / L0: what happened
→ L1: what changed the trajectory
→ L2: what reusable rule appeared
→ Errorbook: what failed, why, risk, mitigation
→ Case Library: how to reproduce it
→ Stress Test: how to expose it deliberately
→ Mitigation Experiment: whether an intervention works
→ Regression Test: whether the failure returns
```

For `HISTORICAL-FAILURE-BENCHMARK-v1`, the public boundary is crossed only after
the Errorbook layer: 89 reviewed correction chains and 18 raw categories are
compressed into 12 mechanism clusters, then reconstructed as 24 synthetic
public-safe minimal-pair cases. The repository contains the reconstructed cases,
not the underlying evidence corpus.

The repository does not publish private L0/L1/L2 material. It publishes public-safe method cards and reproducible cases derived from reviewed sources.
