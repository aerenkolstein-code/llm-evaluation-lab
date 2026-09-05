# Independent QA Lessons from B2

Two B2 changes in this repository exposed the same engineering failure mode from different directions:

- the multi-model measurement contract in [PR #32](https://github.com/aerenkolstein-code/llm-evaluation-lab/pull/32); and
- the blind-handoff possession protocol in [PR #33](https://github.com/aerenkolstein-code/llm-evaluation-lab/pull/33).

Both reached points where tests were green and the implementation looked coherent, yet Independent QA still found contract-level defects. The important lesson is not that tests failed to help. The tests were doing exactly what they had been written to do. The deeper problem was that the thing being tested was not yet equivalent to the thing being claimed.

> **Green inside the wrong contract is still failure.**

This note distills the public engineering lessons from those reviews.

## 1. Test correctness and contract correctness are different questions

A passing suite can show that an implementation is internally consistent. It cannot, by itself, prove that the implemented rules are the intended rules.

That distinction was visible in the measurement-contract work. Early versions had deterministic tests and exact-head CI, but review still found missing or underspecified measurement semantics. The implementation could consistently calculate a result while still calculating the wrong quantity.

A useful review model therefore separates at least four questions:

1. **Contract completeness** — did every required semantic obligation become an explicit artifact, field, rule, or invariant?
2. **Implementation correctness** — does the code implement that contract correctly?
3. **Adversarial correctness** — can a plausible counterexample or attacker satisfy the implementation while violating the intended claim?
4. **Integration and evidence correctness** — are the observed results bound to the exact code surface, execution surface, and review state being discussed?

A mature evaluation system needs all four.

## 2. Critical semantics should be explicit and machine-checkable

Human readers are very good at inferring meaning from nearby fields and prose. Long-lived systems should not depend on that ability for load-bearing semantics.

In the measurement contract, concepts such as benchmark applicability, comparison lanes, exclusion rules, and adjudication authority needed to be represented directly rather than inferred from combinations of other metadata.

This leads to a general rule:

> If a concept can change a denominator, comparison set, authority decision, claim ceiling, or acceptance result, make it a first-class machine-checkable value.

Good candidates for explicit representation include:

- case and family identity;
- applicability and non-applicability;
- requested versus resolved model identity;
- terminal-state meaning;
- inclusion and exclusion rules;
- weighting rules;
- uncertainty method;
- adjudication authority and escalation order; and
- evidence provenance.

The goal is not to maximize schema size. The goal is to eliminate hidden semantics that future code or reviewers could reinterpret without noticing.

## 3. Measurement bugs are often more dangerous than crashes

A crash is obvious. A measurement-definition bug can be stable, reproducible, and wrong.

One important example was `UNKNOWN`. Treating every `UNKNOWN` result as globally non-scorable would be simple, but it would erase distinctions between cases where preserving uncertainty is correct, cases where an unjustified unknown is itself a model failure, and cases where the evaluator lacks enough evidence to decide.

Those outcomes have different meanings for the model-failure denominator.

The broader lesson is to freeze a truth table before implementing aggregation whenever a benchmark contains states such as:

```text
PASS
FAIL
UNKNOWN
ERROR
NOT_EVALUABLE
NOT_APPLICABLE
```

For each state, define at least:

```text
Does it enter the numerator?
Does it enter the denominator?
Is the answer family-dependent?
What evidence resolves the state?
What happens when the evidence remains insufficient?
```

Only then should the aggregator be implemented.

## 4. A proof must prove the exact claim, not a nearby proxy

PR #33 exposed the same problem in security form.

The intended claim was that a returning party actually possessed the matching private key. An early protocol allowed the private side to know the challenge material before the runner encrypted it. The happy path still performed a decryption, so a normal test could show that decryption worked. But acknowledgement acceptance did not actually depend on that decryption.

A cooperating party that already knew the challenge could produce the accepted acknowledgement without possessing the target private key.

The corrected protocol changed the dependency structure:

1. the runner accepts the input payload;
2. the runner generates a fresh challenge that the private side does not know;
3. the runner encrypts that challenge to the bound return public key;
4. the private side must recover the challenge using the matching private key; and
5. the acknowledgement is derived from the recovered challenge.

Now the claimed capability is a necessary condition for producing the accepted proof.

The reusable review question is:

> If an adversary lacks the capability we claim to prove, but knows every other allowed piece of information, can it still produce an accepted result?

If the answer is yes, the protocol proves a proxy, not the claim.

## 5. Negative and adversarial tests often carry more information than another happy-path test

The strongest regression added after the blind-handoff defect did not merely add another successful decrypt-and-ack path. It reconstructed the strongest plausible bypass: a party with all pre-shared or public material but without the matching private key.

That test directly attacked the necessary condition of the proof.

This pattern generalizes beyond cryptography. High-value adversarial tests can ask:

- Can an excluded benchmark case re-enter through a different identifier?
- Can a model silently resolve to a different version and still appear valid?
- Can `UNKNOWN` be coerced into a favorable denominator treatment?
- Can a judge output become final authority despite being declared advisory?
- Can a stale or replayed artifact satisfy a fresh-run contract?
- Can a result be accepted when the evidence receipt points to a different code surface?

The best adversarial test is often the smallest executable version of the most damaging plausible shortcut.

## 6. Evidence needs a surface, not just a number

A statement such as `241 tests passed` is incomplete evidence.

During the measurement-contract work, different test counts were valid on different surfaces: an isolated candidate tree and a current-main merge integration surface can legitimately have different totals. The counts are only meaningful when their execution context is named.

A useful evidence receipt should bind at least:

```text
Test surface
Exact commit or tree
Test count and result
Execution run or job
```

For benchmark work, also bind the measurement contract that defines applicability, denominators, weighting, and uncertainty.

For security proofs, bind the threat claim and the negative/adversarial test that demonstrates the claimed capability cannot be bypassed.

## 7. Review should reconstruct the claim, not rerun the developer's checklist

Independent QA adds the most value when it does more than rerun the same tests used during implementation.

A strong review reconstructs the chain independently:

```text
Claim
→ governing contract
→ observable evidence
→ implementation dependency
→ plausible bypass or counterexample
→ acceptance decision
```

For measurement work, this means asking whether the metric actually measures the stated failure concept.

For a proof protocol, it means asking whether the claimed capability is logically necessary for acceptance.

For evidence provenance, it means asking whether the reported result came from the exact tree and execution surface under review.

This is why an engineering self-check can be green while Independent QA still rejects the change. The two stages answer different questions.

## 8. History should remain immutable when the current implementation is repaired

A later repair can improve the current protocol. It cannot make an earlier execution retroactively satisfy conditions that were not true at the time.

PR #33 preserved that distinction: the durable protocol was repaired, while the historical execution remained non-scorable rather than being relabeled as a valid benchmark sample.

This is a general evidence rule:

> **Current repair does not rewrite historical truth.**

Use new corrections, qualifications, or superseding artifacts when interpretation changes. Do not silently overwrite the original state.

## 9. Exact-head review should treat the reviewed commit as a sealed artifact

Once Independent QA passes an exact commit, that pass belongs to that commit.

Any code change after review should invalidate the previous technical approval unless the review contract explicitly permits it. Mechanical repository actions can be treated separately, but the reviewed code identity should remain stable.

A robust pre-merge sequence is therefore:

```text
Independent QA passes exact head
→ wait for explicit merge authorization
→ refresh PR head and current base
→ confirm reviewed head is unchanged
→ perform only required mechanical state changes
→ merge with an expected-head guard
→ read back merged state and parents
```

This reduces time-of-check/time-of-use drift between review and integration.

## 10. A compact reusable checklist

Before declaring a high-stakes evaluation or proof change green, ask:

### Contract

- Is every load-bearing semantic explicit?
- Are outcome states and denominator rules frozen?
- Are identity, applicability, exclusions, and authority ordering machine-checkable?

### Implementation

- Do positive tests demonstrate the intended normal path?
- Do negative tests demonstrate that missing prerequisites fail closed?

### Adversarial review

- What is the strongest plausible bypass?
- Can a party lacking the claimed capability still pass?
- Can a favorable metric be produced by changing classification rather than behavior?

### Evidence

- Is each result bound to an exact commit/tree and test surface?
- Are test counts distinguishable across isolated and integration surfaces?
- Are historical results preserved without retroactive relabeling?

### Integration

- Is the reviewed head unchanged?
- Is merge authorization separate from technical QA?
- Does merging code avoid implicitly authorizing live execution, credentials, spend, or a later phase?

## Closing principle

PR #32 and PR #33 were different engineering problems, but they converged on one principle:

> **Do not only verify what the system did. Verify that what it did is actually equivalent to what the system claims to measure, prove, or authorize.**

That is the difference between a green implementation and an auditable evaluation system.
