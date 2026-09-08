# SIQ Agent Security v0.3.0-rc.1 — prepared prerelease

Hackathon candidate: a **research / competition candidate**, not production certification.

Secure Agent uses Dynamic Agent Skills, StepFun task planning and NVIDIA DGX Spark local analysis. SIQ independently authorizes actions using Trusted Intent, trusted Context and Parameter Provenance. EffectEvidence separates actual scoped effects from tool claims before Completion is established.

Source: `d1277116e8291e72b09b0462a19d0268b68bf46c`. Four daemon cross-builds: linux-arm64, linux-amd64, darwin-arm64, windows-amd64.exe. The complete candidate was extracted and exercised on DGX linux-arm64. Cross-build ≠ native production validation.

Archive SHA256: `205957fbba10b1019d826232cd004c19ec2444d1519a70bd03137375075369a1`. Included scoped CycloneDX SBOM, Skill inventory, source identity and checksums. `publisher_signing = unavailable`; hash verification ≠ publisher authentication. This RC does not inherit the old v0.2.0 publisher signature.

Known limits: same-UID processes are not OS-isolated; Python ToolGateway is not an OS sandbox; effects use controlled file/receiver fixtures; platform validation is limited; remote StepFun remains an external trust boundary. No universal SaaS proof, general semantic provenance, Windows production certification, production HA, or statistical guarantee from small model cohorts.
