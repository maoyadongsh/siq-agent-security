# Release authentication

No real publisher seed is configured in the supported task/release environment variables checked during this cycle. The candidate therefore states `official_signature=false`. No test, historical-development or newly generated temporary key is substituted for publisher authentication.

SHA256SUMS verifies downloaded byte integrity. GitHub's release page and immutable source commit identify the repository location and version; they are not a claim of the project's historical Skill publisher signature. The existing signed v0.2.0 Skill manifest authenticates its own stated subject only. No GitHub artifact attestation was generated in this cycle and no claim of one is made.

Receipt-chain verification proves internal experiment consistency under the recorded keys, separately from release provenance and separately from whether an experiment supports a scientific conclusion. A signed release would not enlarge same-UID isolation, observer scope or statistical claims.
