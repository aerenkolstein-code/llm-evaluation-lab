# Privacy and Evidence Boundary

This repository is public-safe by design.

## Excluded material

Do not commit:

- private conversation Raw/L0 material;
- private archive locators or credentials;
- API keys, tokens, passwords, OTPs, or payment secrets;
- private client documents;
- family, health, financial, or relationship records;
- hidden judge registries or private answer keys;
- model-provider secrets or credential-bearing request/response dumps.

## Search Cup specific boundary

SEARCH-CUP entrants must not receive hidden-registry contents, private drilling tables, Drive credentials, or provider secrets. Search traces and submissions should remain content-safe and auditable.

The v2.2 architecture additionally requires provenance labels that distinguish:

- entrant model identity;
- retriever/search backend identity;
- Live Web vs Frozen Corpus environment;
- Search Spec/version;
- search call/turn budget;
- evidence URLs or frozen-corpus references;
- UNKNOWN / verification status.

Dedicated search-stack challenge results must not be silently attributed to the general-purpose entrant model when the backend performs its own query decomposition, rewrite, aggregation, or synthesis.

Frozen corpora and judge/reference sets may have private construction artifacts; only public-safe derived fixtures, hashes, versions, or explicitly approved evaluation assets belong in the public repository.
