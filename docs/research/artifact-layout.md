# Research archive layout

Proposed versioned archive members: `source/` (exact clean Git archive), `licenses/` (project scope and every bundled third-party notice), `evidence/` (whitelisted reports plus manifests), `reproduction/` (instructions and environment matrix), `citation/` (CFF and exact-commit reference), and optional `media/` (separately reviewed, attributed video). Binary artifacts additionally carry the existing four-platform package layout, precise native-validation scope and complete SBOM for bundled assets.

Private state and provider/model credentials are never members. Model weights and platform images are not redistributed. A source-only release is not described as a validated binary release. Source archives without Git history do not erase an exposed key from existing public repository history.

GitHub release assets and Zenodo archival files must be checked independently after upload; do not assume automatic GitHub integration captures arbitrary attachments. Record real version DOI and concept DOI only after readback. Do not insert placeholder DOI links or artifact badges. A corrected archive gets a new version, an erratum and its own digest; the prior version remains identifiable.
