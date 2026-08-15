# Methodology

The lab predeclares case inputs, expected behavior and metrics before comparing baseline and treatment.

```text
Observe → Diagnose → Intervene → Stress-test → Measure → Regression-test
```

The first artifact uses invariant transformations: child wording and order change while the required closure decision does not. A valid treatment must also preserve the sensitive all-terminal case, avoiding the trivial strategy “never close anything.”

Future model-based runs will keep the same separation between case owner, policy under test, grader, mitigation and checked-in result.

