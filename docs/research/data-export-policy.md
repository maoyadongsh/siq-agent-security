# Public research evidence export

Export only the existing runners' public reports and verifier summaries after content review and calibrated secret scanning. Preserve source/corpus/verifier digests, all attempted case IDs, errors, exclusions, timestamps, public verification keys and aggregate results. Do not copy entire state/output directories as a convenience.

Exclude service.json, pairing codes, signing seeds, private keys, provider configuration, HTTP authorization headers, raw sensitive prompts, private receiver state, user paths unrelated to reproduction and third-party data without permission. Browser screenshots require review for pairing tokens and personal data; use a sanitized summary when images are unnecessary.

Synthetic .example contacts are intentionally retained for provenance comparisons. Do not replace just one side of a same-value comparison. Use stable replacements when a real identifier must be redacted, record the transformation and avoid claiming signatures still verify after editing signed content. Preserve a restricted original; publish a newly identified sanitized artifact with its own digest.

Outside contributors should submit the minimal sanitized reproduction and explicitly approve public redistribution of their original evidence. A security report's existence does not authorize public disclosure. Model API terms and input-data rights are separate from the project's source license.
