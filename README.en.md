<p align="center">
  <img src="site/siq-shield.svg" width="96" height="96" alt="SIQ blue shield logo" />
</p>

<h1 align="center">SIQ Agent Security</h1>

<p align="center"><strong>Secure Runtime for Agent Skills</strong><br />
Agent security research and implementation: permissions, runtime checks and execution evidence</p>

<p align="center">Agent Skills define what agents can do. SIQ defines what they are allowed to do.</p>

<p align="center">
  <a href="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI · main" /></a>
  <a href="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/research.yml?query=branch%3Amain"><img src="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/research.yml/badge.svg?branch=main" alt="Research reproduction · main" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/code-Apache--2.0-001840?style=flat" alt="Project-owned code: Apache-2.0" /></a>
  <a href="https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.1"><img src="https://img.shields.io/badge/release-0.3.1%20signed-7c5a0c?style=flat" alt="Signed release 0.3.1" /></a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> · <a href="research/README.md">Research map</a> · <a href="#research-and-evidence">Research evidence</a> · <a href="#components-and-integrations">Integrations</a> · <a href="#contributing-and-next-steps">Contributing</a>
</p>

---

**SIQ Agent Security is an open-source research project on agent authorization boundaries and execution evidence, with a working security management system for individuals and organizations.** It helps individuals and organizations inventory agents in local or connected environments, review tool and resource permissions, manage installation and updates, and check authorization on integrated execution paths. Users keep working in their existing agents while SIQ provides permission management, action approval and task evidence.

The research asks how model proposals receive independent authorization, how provenance constrains execution, and how observed effects establish task completion. The implementation links trusted Intent, parameter provenance, Skill Execution Context (SEC), a unique post-approval execution reservation and effect verification: who authorized the action, which installation it belongs to, and what actually happened. Root-level [research/](research/README.md) connects literature, questions, methods, experiments, findings and governance; [evaluations/](evaluations/README.md) separates research observations, engineering acceptance and external reproductions.

The **personal client** provides a local service and browser console for agents, Skills and tasks. The **enterprise control plane**, Edge and Connectors support environment inventory, policy approval and deployment readback. Current delivery focuses on the personal client, with the signed `0.3.1` regular release available; convenient LAN team-device workflows remain planned.

**Product focus: user-authorized security management throughout the Agent and Skill lifecycle.** Agents plan tasks; the SIQ runtime checks specific actions against trusted authority and associates signed receipts with observed effects where collection is integrated. The project also maintains reproducible provenance/effect research and DGX Spark/OpenShell integrations. Its deterministic research demonstration runs on ordinary Linux without model API keys or a GPU.

> **Signed installation package (2026-09-19):** [0.3.1 release (Latest)](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.3.1) provides an offline bundle, signed Skill and four target binaries, built from main commit `f3d9c3f` and signed with the existing publisher key. Download the Release installation assets; GitHub automatic source archives and `skills/siq-agent-security/` remain development source. Linux ARM64 passed native first-start and tamper-rejection checks; the other targets have build and signature-pin verification only. See [installation instructions](docs/signed-release-packaging.md) and [signing/publication evidence](docs/evidence/releases/0.3.1/README.md).

[Application modules](apps/README.md) · [Documentation map](docs/README.md) · [Current development](docs/development/current.md) · [Repository reorganization](docs/development/reorganization-progress.md) · [Platform delivery](platforms/README.md) · [Evaluations and external reproduction](evaluations/README.md)

## Product direction and support status

The product follows **discovery and review → admission and authorization → execution and approval → traceability and maintenance**. Personal features include asset inventory, Skill install/update/removal, permission review, task activity, signed receipts and opt-in raw-content management. Enterprise features include environment and Edge enrollment, multi-tenant inventory and risk management, policy approval, deployment readback and audit. The immediate priority is native acceptance of the integrated personal features on a fixed release candidate, followed by team-device workflows.

The local Go service serves the personal browser console, the SIQ Skill provides operating guidance, and adapters connect host tool calls. Skill installation, asset discovery and runtime protection are confirmed separately; actual enforcement depends on the integrated host paths and platform evidence.

**Repository snapshot, 2026-09-19 (source for the regular `0.3.1` release fixed at main commit `f3d9c3f`; later publication records and README updates retain that identity):** The macOS stage, OpenShell policy and v6 constrained execution, Linux dual-host fixes and personal-client work are integrated. Windows #80–#83 added Writer, migration recovery, DACL, resource facts, host management and client lifecycle; #90 added junction verification and content-hash regressions. See the [local integration audit](docs/local-development-integration-audit-20260919.md), [Windows review](docs/windows-main-integration-review-20260919.md) and subsequent [source/release boundary update](docs/skill-source-release-boundary-20260919.md). The regular 0.3.1 release is published as Latest; all eight assets have been downloaded and verified. Historical component and native evidence remains bound to its recorded candidates; it does not establish full acceptance of this release.

| Scope | Current evidence | Remaining work |
| --- | --- | --- |
| Linux personal management | Console, lifecycle, Skill update and selected native OpenClaw/Hermes paths have staged evidence; the sixth local candidate passed the installed B02 and combined R07/R04 journeys; raw-retention and task-export acceptance is complete for the current scope; the 0.3.1 bundle passed Linux ARM64 package verification, fresh-state startup from its INSTALL.md, pairing, console and graceful-stop checks | The stock OpenClaw post-approval checkpoint, desktop visual checks and complete stable-release acceptance; the supplemental continuous 12-hour admin-session leg is out of scope and is not claimed as passed |
| macOS | LaunchAgent lifecycle, staged OpenClaw/Hermes/WorkBuddy work and independent review fixes are merged; 0.3.1 includes a manifest-signed arm64 binary | Same-candidate host retests, native installation/upgrade and Apple signing/notarization; the project manifest signature is not notarization |
| Windows | Writer, migration recovery, DACL, resource/identity checks, host management, task install/upgrade/rollback and junction protection are merged; 0.3.1 includes a manifest-signed amd64 binary and Skill | Native installation/upgrade and same-candidate host retests; historical OpenClaw evidence uses a WSL Agent, Hermes uses native CLI, and minimal WorkBuddy native I/O does not establish full approval recovery, desktop update or repeatability |
| OpenClaw / Hermes / WorkBuddy | Linux delivery scope is OpenClaw and Hermes; selected real host paths have evidence | WorkBuddy is in scope only on macOS/Windows; no CodeBuddy result can establish WorkBuddy acceptance |
| LAN team management | Optional enterprise Control API, Edge and Connectors already exist | Team device onboarding, unified management and acceptance after the personal phase |

Personal Skill import accepts local directories, local ZIP files and policy-compliant HTTPS ZIP URLs. The Git repository import option remains disabled pending real-network acceptance; an arbitrary repository homepage is not an installation URL.

New CodeBuddy integration work is cancelled across all platforms. Historical records retain safe inspection, denial, revocation and uninstall paths. Linux WorkBuddy is outside the current delivery scope.

The v6 OpenShell task endpoint is now in main. A policy-apply response alone is not proof of task execution: the execution path must bind its CLI and endpoint, confirm policy and instance readback, and recheck authorization before starting work. The sixth local candidate completed a zero-fail 373-step D05 run and a 57/57 B3 functional journey. Historical gateway and performance evidence still belongs to its recorded candidate; remote single-task stop confirmation, the remaining external/protocol conditions, performance and complete stable-release acceptance remain open. See the [current Linux taskbook](docs/linux-dual-host-integration-development-taskbook-20260918-205119.md), its [progress ledger](docs/linux-dual-host-progress-20260918.md), the [v6 ledger](docs/personal-v6-integration-progress-20260917.md), and the [original development ledger](docs/personal-experience-development-progress-20260910.md) for exact scope. Discovery does not mean protection is enabled; enforcement depends on the integrated tool paths.

OpenClaw versions are tracked separately as well. The archived Linux validation environment used a shared 2026.5.12 installation. The sixth Linux candidate also ran the public OpenClaw 2026.9.4 CLI under isolated Node 24.18.0 through the [controlled-start entrypoint](docs/openclaw-controlled-start-linux-20260919.md), completing the product-managed native journey 22/22. That result belongs to a digest-pinned temporary patch copy: stock 2026.9.4 still lacks the post-approval, pre-execution final-parameter recheck contract required by SIQ. It is therefore not a default upgrade, an upstream approval capability, or formal release support. A version bump does not raise the protection level without same-version, same-candidate evidence.

## Core value

**Core outcome: manageable permissions, checked execution and traceable results.** Users can review what is allowed, check whether an integrated action is authorized, and inspect receipts and observations to establish what happened. These capabilities support Trusted Agent Execution.

| User concern | Implemented product and technical mechanism | Practical use |
| :--- | :--- | :--- |
| **Manage assets and changes** | Asset discovery and attribution, Skill admission checks, installation/update previews, confirmation and removal | Review sources and permission changes throughout the lifecycle |
| **Authority independent of the model** | A Go runtime checks Grant / Intent, session bindings and approvals before execution; model proposals cannot expand permissions | Auditable authorization boundaries for automated operations |
| **Same value, different provenance** | Trusted Context and parameter provenance bind to actions; identical recipient values can be allowed or denied based on trusted-database / MCP origin | Constrain recipient substitution and unauthorized delivery induced by tool results |
| **Completion grounded in effects** | Signed receipts associate actions; independent file and controlled-receiver observers distinguish tool success, observed effects and task completion | Evidence for delivery acceptance, fault diagnosis and execution audits |

Potential applications include enterprise Agent permission governance, research/report delivery and tool-platform integration. The local runtime, adapters and optional enterprise control plane provide the current foundation; scale, external SaaS effect verification and commercial returns still require validation in specific deployments. Assess research contributions through the [research questions](docs/research/research-questions.md) and [technical report](docs/research/technical-report.md); no priority or peer-reviewed novelty is claimed.

> [!IMPORTANT]
> **Research source prerelease with a Sigstore digital signature**
>
> [research-v0.1.0-rc.1](https://github.com/maoyadongsh/siq-agent-security/releases/tag/research-v0.1.0-rc.1) includes `SOURCE-INFO.json`, `SHA256SUMS` and `SHA256SUMS.sigstore.json`, with no newly compiled binaries or model weights. The signature binds the checksum manifest to this repository's GitHub Actions release workflow identity, covering the source archive and metadata. Verify the signature before checking file hashes: [verification instructions and signature scope](docs/research/release-authentication.md).

<details>
<summary>Initial research release source and identity</summary>

The research source prerelease is fixed at [`aefab111`](https://github.com/maoyadongsh/siq-agent-security/commit/aefab111c7fcad9075c8f429f97c9eab519dcd22); later README and publication-record updates do not change that identity.

A detached signature was added on 2026-09-09 without modifying the original assets. The `official_signature=false` field in `SOURCE-INFO.json` preserves the initial packaging status; see the separate [Sigstore signing and verification record](docs/research/evidence/release-signing-20260909.json).

</details>

## Start here

To evaluate source distribution through `vercel-labs/skills`, use the [pinned compatibility checks](docs/research/skills-distribution.md). This tool copies development source from a Git commit; it does not replace the [signed installation package](docs/signed-release-packaging.md). Historical CodeBuddy/Trae directory-copy checks do not expand current product support.

| Your goal | Entry point | What to expect |
| :--- | :--- | :--- |
| Manage local agents and Skills | [Signed package installation](docs/signed-release-packaging.md) · [Source build](#personal-console-linux-source-build) · [Operations guide](AGENTSHIELD.md) | Start the local service, pair the browser and enable protection within verified platform scope |
| Govern organizational assets and policies | [Control-plane setup](docs/control-plane.md#快速开始) · [Production runbook](docs/enterprise-production-runbook-v1.md) | Enroll environments and Edge devices, review assets, approve policies and inspect deployment evidence |
| Try the complete flow | [Quick start](#quick-start) | A local demonstration without model keys |
| Reproduce and evaluate | [Reproduction guide](REPRODUCIBILITY.md) · [Research index](docs/research/README.md) | Fixed cases, evaluation protocols and evidence |
| Integrate your Agent | [Components and integrations](#components-and-integrations) | Runtime, adapter and contract entry points |
| Contribute to research | [Contributing](CONTRIBUTING.md) · [Community tasks](docs/research/community-backlog.md) | Clearly scoped starting points |

## What you can verify

Consider a task to analyze a repository, write a report and deliver it to a specified contact. The Agent dynamically selects research, report and delivery Skills. The demonstration exposes four observable outcomes:

| Scenario | Check | Expected result |
| --- | --- | --- |
| Normal delivery | Task authority, trusted contact, file and receiver effects | `verified`: required effects have been verified |
| MCP recipient injection | An untrusted tool result proposes a different recipient | `blocked`: the unauthorized action is stopped |
| Same value, different provenance | Identical recipient values from a trusted database and MCP | Trusted path allowed; MCP path denied |
| False tool success | The tool reports success, but the controlled receiver has no corresponding event | `incomplete`: a required effect is missing |

These demonstrations use explicit model fixtures to drive real SIQ components. They verify specific security paths; they do not measure prompt-injection attack success rates against a real model.

## How it works

### Components and authorization chain

This diagram shows the current local-runtime and enterprise control-plane relationships. Managed instances enroll real host sessions; trusted Context, parameter provenance and an optional Skill Execution Context (SEC) enter server-side verification. The optional enterprise deployment uses its own identity and service; running both consoles does not automatically synchronize authority. The personal runtime also has an independent OpenShell integration, described in the [Chinese integration overview](README.md#dgx-spark-与-nvidia-openshell-深度适配).

```mermaid
---
config:
  themeVariables:
    fontSize: 16px
  flowchart:
    nodeSpacing: 20
    rankSpacing: 40
    wrappingWidth: 170
---
flowchart TB
    subgraph Local[Personal integration: host and local service]
        direction TB
    Human[Operator] --> Console[Local console / management API]
    Skill[SIQ Skill: operating guidance] --> Agent[Application Agent]
    Candidate[Candidate Skill] --> Admission[Static admission / content digest]
    Admission --> Console
    Console --> Authority[Signed Grant / Intent / session binding]
    Agent --> Adapter[Host runtime adapter]
    Adapter --> Identity[Managed instance identity / native session enrollment]
    Identity --> Gate[Local authority and decision engine]
    Adapter -->|Concrete action and parameters| Gate
    Authority --> Gate
    Context[Trusted Context / parameter provenance / optional SEC] --> Gate
    Gate --> Decision[Adapter handles decision / host gate retained]
    Decision -->|Execution conditions met| Tool[Host tool]
    Tool --> Observe[Call result correlation / Observation]
    Gate --> Receipts[Signed decision and execution receipt chain]
    Observe --> Receipts
    Receipts --> View[Console review and trace]
    Console -.->|Explicit integration| LocalBackend[Local OpenShell adapter / policy load and readback]
    end

    subgraph Enterprise[Optional enterprise deployment: separate identity and service]
        direction TB
        Connectors[Read-only Connectors] --> Edge[Edge: task verification / evidence signing]
        Edge --> Control[Control API / Worker]
        EnterpriseUI[Enterprise console / human approval] --> Control
        Control --> DB[(PostgreSQL / audit / outbox)]
        Control --> Backend[Enterprise backend adapter / policy readback]
    end
    Local ~~~ Enterprise
    classDef authority fill:#fff8e6,stroke:#9a7417,color:#513b08
    classDef runtime fill:#eaf1fb,stroke:#43658f,color:#142f53
    classDef evidence fill:#eaf6f1,stroke:#3b7965,color:#174d3d
    style Local fill:transparent,stroke:none
    style Enterprise fill:transparent,stroke:none
    class Human,Authority,Identity,Context authority
    class Admission,Gate,LocalBackend,Control runtime
    class Observe,Receipts evidence
```

### Task execution and effect verification

```mermaid
---
config:
  themeVariables:
    fontSize: 16px
---
flowchart TB
    Task[User task] --> Proposal[Agent plan / Skill selection / tool proposal]
    Authority[Grant / Intent / provenance and context constraints] --> Gate[SIQ pre-execution checks]
    Proposal --> Gate
    Gate -->|allow or host-supported redact| Tool[Execute approved parameters within host gate]
    Gate -->|deny / unmet conditions| Stop[Block this call]
    Gate -->|hold| Approval[Local approval / host-specific resume protocol]
    Approval --> Recheck[Recheck current authority and final parameters]
    Recheck -->|Invalid / expired / revoked| Stop
    Recheck -->|Valid| Reserve[Atomically persist unique signed execution reservation]
    Reserve -->|Reserved with unambiguous response| Tool
    Reserve -.->|Reserved but execution unconfirmed| Uncertain[uncertain: inspect facts / no blind replay]
    Tool --> Observation[Host result report / Observation]
    Observation --> Receipts[Correlated action / decision / reservation receipts]
    Gate --> Receipts
    Reserve --> Receipts
    Tool -.->|An integrated observer samples effects| Effect[File or receiver material / EffectEvidence]
    Requirements[Effect requirements in signed Intent] --> Completion[SIQ validates material and actions / evaluates requirements]
    Receipts --> Completion
    Effect --> Completion
    Completion --> Result[verified / incomplete / conflicting / unknown]
    classDef authority fill:#fff8e6,stroke:#9a7417,color:#513b08
    classDef runtime fill:#eaf1fb,stroke:#43658f,color:#142f53
    classDef evidence fill:#eaf6f1,stroke:#3b7965,color:#174d3d
    class Authority,Approval,Requirements authority
    class Gate,Recheck,Reserve,Completion runtime
    class Observation,Receipts,Effect,Result,Uncertain evidence
```

- **Before execution**: statically inspect Skills and pin content digests. Constrain actions with Grants, Intent, instance/session identity, trusted Context and parameter provenance. Verify SEC when trusted Skill attribution is required; a name or installation path alone is not proof. Model output cannot create effective permissions.
- **During execution**: enforce decisions at integrated entry points while retaining the host gate. Supported hold-resume paths recheck authority and final parameters after local approval, then persist a unique reservation before attempting execution. Denial, expiry, revocation or missing resume capability blocks the call. Reserved but unconfirmed execution remains `uncertain`, without automatic replay.
- **After execution**: correlate results and signed receipts by action, decision and reservation. Integrated file or receiver observers collect effect material. Completion checks signed Intent requirements, action authority and valid material; missing or conflicting evidence cannot be shown as completed.

Dashed edges denote explicit integration or conditional paths, not universal effect coverage. Approval and host-gate ordering follows each adapter protocol; stock OpenClaw and a pinned checkpoint-patched copy have separate acceptance. `redact` requires host parameter-rewrite support; other mappings follow the adapter contract.

Ordinary Observation correlation and independent EffectEvidence establish different things. `uncertain` is an execution-reservation state, not a fifth Completion outcome. See the [technical report](docs/research/technical-report.md), [contracts](packages/contracts/README.md) and [security boundaries](#security-boundaries) for architecture and protocol details.

## Quick start

For the signed version, download the [0.3.1 offline bundle](https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.3.1/siq-agent-security-0.3.1-bundle.zip) and follow the [installation instructions](docs/signed-release-packaging.md) to extract it, verify the package and start the local service. The bundled `INSTALL.md` now includes first-start instructions: verify the package, then use the verified binary’s `start` command to initialize state and start the service. Direct bootstrap use still requires initialization beforehand. No local Go/UI compilation is needed. The source-development and research steps remain below; GitHub automatic Source code archives are not signed installation packages.

### Personal console: Linux source build

This uses the foreground entry point available on current `main`. Prepare Git, Go **1.26.6**, and Node.js **22 / npm**; no enterprise Control API or PostgreSQL is required. Run from the repository root (if needed, first use the `git clone` and `cd` commands in the demonstration below):

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build:local
mkdir -p .tmp/personal-bin
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build \
  -o "$PWD/.tmp/personal-bin/siq-agent-security" ./cmd/agentshield

export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/.tmp/personal-state"
.tmp/personal-bin/siq-agent-security start --port 47611
```

Keep the terminal running, open **http://127.0.0.1:47611/overview**, and enter the one-time pairing code printed by the service. If the code expires, open another terminal at the same repository root and run:

```bash
export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/.tmp/personal-state"
.tmp/personal-bin/siq-agent-security pair --port 47611
```

`start` initializes or reuses this directory's configuration and serves in the foreground on first use; press `Ctrl+C` to stop it. If a matching instance for the same directory is already running, it returns that instance's status; use `pair` above for a fresh pairing code. This example stores state in `.tmp/personal-state`; reuse the same path and preserve any needed data before cleaning `.tmp`. See the [operations guide](AGENTSHIELD.md) for background setup, upgrade and recovery commands and platform limitations; keep the selected state directory and instance consistent.

<details>
<summary>Frontend development and disconnected-state troubleshooting</summary>

Keep the Go service above running, then use another terminal:

```bash
npm --prefix apps/web run dev:local
```

Open the address printed by Vite. The development proxy targets `http://127.0.0.1:47611`; `dev:local` starts only the frontend. If the console reports a disconnected or unreachable decision API, check the local Go service and port, then pair the browser. The enterprise frontend uses separate Control API configuration. The embedded UI is served directly by Go and does not require Vite.

</details>

### 1. Run the research demonstration without model keys

The validated entry environment is Linux with Git, Go **1.26.6**, Python **3.12+**, and Node.js **22 / npm**. Initial dependency and toolchain installation needs network access. Use a fresh clone: the launcher refuses to overwrite existing demonstration state.

```bash
git clone https://github.com/maoyadongsh/siq-agent-security.git
cd siq-agent-security

bash scripts/hackathon/start.sh --mode test --port 47621
bash scripts/hackathon/healthcheck.sh
bash scripts/hackathon/pair.sh
```

The launcher installs locked Web dependencies and builds the local UI and Go binary. Open **http://127.0.0.1:47621/demo**, enter the one-time pairing code printed in your terminal, and select a scenario from the table above. Keep pairing codes and service state files on your machine.

> [!NOTE]
> Pass `--mode test` explicitly: the launcher's default `demo` mode uses configured real models. To pin the first release, run `git switch --detach research-v0.1.0-rc.1` before starting.

Stop this demonstration instance when finished:

```bash
bash scripts/hackathon/stop.sh
```

Before restarting, archive the instance's previous state as described in the [reproduction guide](REPRODUCIBILITY.md). That guide also covers occupied ports, pairing issues and environment diagnostics.

### 2. Reproduce the fixed benchmark

Install **uv** as well, then run these commands from the repository root. Use fresh state and output directories for every attempt.

```bash
(cd apps/control-api && uv sync --dev --locked)
mkdir -p .tmp/research-bin
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build \
  -o "$PWD/.tmp/research-bin/siq-agent-security" ./cmd/agentshield

apps/control-api/.venv/bin/python benchmarks/hackathon/run.py \
  --binary .tmp/research-bin/siq-agent-security \
  --state-root .tmp/my-research-controls \
  --out .tmp/my-research-results/controls.json

apps/control-api/.venv/bin/python benchmarks/hackathon/verify.py \
  .tmp/my-research-results/controls.json \
  --out .tmp/my-research-results/verification.json
```

The default cohort contains all **23 fixed control cases**. Check expectation violations and verifier results: `blocked` for an attack or `incomplete` for false tool success can be the correct outcome. Retain failed attempts and review reports against the [evidence export policy](docs/research/data-export-policy.md) before sharing. Do not upload private state directories.

### 3. Optional: use real models

<details>
<summary>Show the StepFun + DGX Spark setup path</summary>

The existing real-model demonstration uses **StepFun `step-3.7-flash` for remote planning** and **Ornith on DGX Spark for local analysis**. This path requires separate model, credential and hardware configuration. Run it separately from the key-free paths and report its results separately.

Start with the [DGX deployment guide](deploy/dgx-spark/README.md), [private model configuration](docs/hackathon/step-plan.md) and [three-track reproduction guide](REPRODUCIBILITY.md). A local failure during confidential analysis must not automatically authorize fallback to a remote model.

</details>

## Research and evidence

Updated through **2026-09-19**. Recent engineering/release checks and historical research reproduction are listed separately. Each result belongs to its recorded source or candidate, environment and test scope; denominators must not be pooled or transferred to other versions.

**Recent engineering and signed-release verification (2026-09-18–19)**

| Archived observation | Result | Evidence and scope |
| --- | --- | --- |
| 0.3.1 signed package | Signature and native startup passed; **3/3** tamper rejections | [Release record](docs/evidence/releases/0.3.1/README.md); source `f3d9c3f`, four binary pins and Skill content, Linux ARM64 final-package start/status/pair/console/stop; other targets have no native installation acceptance for this release |
| 0.3.1 publication and source CI | **8/8** assets match; **6/6** source workflows succeeded | [Public readback](docs/evidence/releases/0.3.1/publication.json), [source CI](docs/evidence/releases/0.3.1/source-ci.json); regular release and Latest; workflow count is not a test count |
| Four-target Skill source checks | **4/4** native targets passed | [Fixed-candidate record](docs/evidence/repository-reorganization-final-20260919/README.md); PR #97 head `bf7dced`, actual merge checkout SHA in each report; Linux amd64/arm64, macOS arm64 and Windows amd64 self-admission, missing-manifest rejection, startup, pairing, console and stop. Source checks do not establish 0.3.0 system-service installation, upgrade or full host acceptance |
| 0.3.0 release package | **14/14** checks passed | [Package verification](docs/evidence/releases/0.3.0/verification.json); source `83fde2d`, official-root verification, tamper rejection and Linux ARM64 installation checks; includes executing the bundled INSTALL.md from empty state through startup, pairing, console and stop; other targets lack native installation acceptance |
| 0.3.0 publication and remote readback | **8/8** asset hashes match | [Publication verification](docs/evidence/releases/0.3.0/publication.json); regular Release, Latest at the time of that readback; four binary pins, Skill signature/content and Linux ARM64 signed-URL download/staging verified |
| 0.3.0 release-source CI | **5/5** workflows succeeded | [Source CI record](docs/evidence/releases/0.3.0/source-ci.json); commit `83fde2d`, ci, research, runtime-security, personal-experience and sonarcloud; separate from native release-asset installation acceptance |
| 0.3.0-rc.1 signed package | **13/13** checks passed | [Package verification](docs/evidence/releases/0.3.0-rc.1/verification.json); source `58ab22e`, official-root checks, six rejection cases, Linux ARM64 bootstrap, console and graceful stop; no native installation acceptance on other targets |
| 0.3.0-rc.1 remote asset readback | **8/8** asset hashes match | [Publication verification](docs/evidence/releases/0.3.0-rc.1/publication.json); four binary pins, Skill content and signature reverified, plus Linux ARM64 signed-URL download and staging |
| Linux installed service and user journey | B02 **16/16**; installed R07 **31/31**, nested R04 **31/31** | [Same-candidate checks](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx02-sec-hold-fix-installed-summary.json); sixth source candidate `67bc48c4…` with a test release trust root; not full user-journey acceptance of 0.3.0 |
| Hermes native CLI and browser approval | **24/24** checks passed | [Combined approval checks](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-browser-approval-native-summary.json); candidate `67bc48c4…`, approval, denial, parameter/object drift, concurrency and revocation; headless browser and synthetic model |
| OpenClaw 2026.9.4 controlled start | **22/22** checks passed | [Managed native CLI checks](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-managed-native-summary.json); candidate `67bc48c4…`, isolated installation and pinned patch; does not establish a post-approval checkpoint in the stock host |
| Browser management-session race repair | Web **117/117**; targeted real-browser checks **2/2** | [Session repair checks](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-summary.json); eighth scoped candidate `a85c76b0…`; does not inherit sixth-candidate systemd/OpenShell acceptance |
| OpenShell D05 native functional matrix | **373** steps: 365 pass / 7 partial / 1 blocked / **0 fail** | [D05 results](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-summary.json); candidate `67bc48c4…`, backend 0.0.83; remote single-task stop remains limited, and zero failures do not establish full acceptance |
| OpenShell B3 functional journey | **57/57** passed | [B3 results](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-b3-summary.json); candidate `67bc48c4…`, policy apply, receipts, denial, revocation and rollback; no performance-budget acceptance |
| PostgreSQL + OIDC/JWKS integration | **27/27** checks passed | [Isolated integration results](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx07-postgres-oidc-jwks-rotation-summary.json); Control API source `2187fea`, rotation, expired-cache rejection and recovery; local PostgreSQL and a test issuer, not customer production acceptance |

**Historical research reproduction and initial release (original run scope preserved)**

| Archived observation | Result | Evidence and scope |
| --- | --- | --- |
| Fixed control cases | **23/23** expectations satisfied | [Report and verification summary](docs/research/result-reproduction.md); controlled fixtures run during development |
| Benign task completion | **5/5** | All benign tasks in the same control report |
| Unsafe target materialization | **0/13** | Cases with a registered unsafe target; a different denominator from benign tasks |
| Receipt and effect-envelope verification | **318** receipts, **20** effect envelopes | [Independent verification output](docs/research/evidence/reproduction-b/verification.json) |
| Browser reproduction on ordinary Linux | **9/9** scenarios passed | [Hosted Ubuntu run](docs/research/evidence/reproduction-a/hosted-linux-identity.json); no GPU or model keys |
| Released-source CI | **31** required checks passed | [Release-source record](docs/research/evidence/release-ci.json); source `aefab111` |

Historical StepFun and Ornith benign-task cohorts each retain later **5/5** results, alongside earlier **4/5** failures in the [original benchmark report](docs/hackathon/benchmark-report.md). These small samples do not establish statistical guarantees and must not be pooled with fixed fixtures or later demonstrations. Hosted CI reproduction is not independent reproduction by an external researcher.

Research entry points: [questions](docs/research/research-questions.md) · [dataset card](docs/research/dataset-card.md) · [evaluation protocol](docs/research/evaluation-protocol.md) · [claims and evidence](docs/research/claims-evidence.md). No published paper, DOI or independent artifact certification is currently claimed.

## Components and integrations

| Component | Responsibility | Entry point |
| --- | --- | --- |
| Secure Agent and research Skills | Task planning and dynamic research / report / delivery selection | [Agent guide](apps/secure-agent/README.md), [Skills](skills/) |
| Local Go runtime and personal console | Admission, authorization, Skill lifecycle, approvals, task/privacy management and signed receipts; the personal UI is embedded in Go | [Personal UI](apps/web/README.md), [runtime guide](apps/agentshield/README.md), [local operations](AGENTSHIELD.md), [development specification](docs/agentshield-dev-spec-v1.md) |
| SIQ Skill and release tools | Operating guidance, manifest verification and secure staging; building and signing installation packages from fixed commits | [Skill source](skills/siq-agent-security/), [release tool](scripts/release/package.py), [installation guide](docs/signed-release-packaging.md) |
| Runtime adapters | OS-scoped Hermes, OpenClaw and WorkBuddy entry points; CodeBuddy is retained only for safe handling of historical configuration and records | [Adapters](adapters/runtime/README.md), [capability matrix](docs/agentshield-capability-matrix-v1.md), [platform scope decision](docs/personal-platform-scope-decision-20260917.md) |
| OpenShell and DGX Spark integration | Deployment checks, local-model configuration, policy authorization/loading/recovery and constrained task execution | [DGX deployment](deploy/dgx-spark/README.md), [OpenShell implementation](apps/agentshield/internal/openshell/), [native evidence](docs/openshell-policy-load-wait-repair-20260916.md) |
| Enterprise control plane | Multi-tenant inventory, evidence, policy approval and Edge coordination | [API module](apps/control-api/README.md), [control plane](docs/control-plane.md), [production runbook](docs/enterprise-production-runbook-v1.md) |
| Edge and Connectors | Configuration, directory, framework, process, container and cluster collection | [Edge](edge/agent/README.md), [Connectors](connectors/README.md), [compatibility](docs/compatibility.md) |
| Contracts and benchmarks | Cross-component data contracts, fixed corpus and evidence verification | [Contracts](packages/contracts/README.md), [Agent benchmark](benchmarks/hackathon/README.md), [runtime benchmark](benchmarks/runtime-security/README.md) |

The local demonstration does not require PostgreSQL, enterprise login or the enterprise API. Collection, tool blocking and native validation are tracked separately for each platform. An adapter's existence does not establish protection across all versions or execution paths. Consult the relevant runbook for production prerequisites and unverified scope.

## Security boundaries

- **No same-UID isolation**: desktop mode cannot prevent a malicious process under the same OS user from reading keys or modifying state. The Python ToolGateway is not an OS sandbox.
- **Limited integration coverage**: authorization checks cover correctly integrated execution paths. Source registration and sensitivity classification still depend on trusted operators.
- **Scoped effect evidence**: file and controlled-receiver observations do not prove delivery across arbitrary external SaaS systems. Missing or conflicting evidence cannot be counted as success.
- **Limited experimental claims**: a small fixed corpus and model fixtures do not establish universal prompt-injection protection, full semantic provenance or production security certification. Cross-compilation is not native validation on every platform.

See the [threat model](docs/threat-model.md), [capability matrix](docs/agentshield-capability-matrix-v1.md) and [dataset card](docs/research/dataset-card.md). Report unpatched vulnerabilities through the private channel in [SECURITY.md](SECURITY.md).

## Contributing and next steps

Contributions are welcome for ordinary Linux reproduction, same-value provenance explanations, fixture diagnostics, metric corrections and negative cases with documented origins. Read [CONTRIBUTING.md](CONTRIBUTING.md), then choose a [starter task](docs/research/community-backlog.md), [Issue](https://github.com/maoyadongsh/siq-agent-security/issues) or [Discussion](https://github.com/maoyadongsh/siq-agent-security/discussions).

Delivery proceeds from the personal experience to LAN team management:

1. **Complete release-candidate acceptance.** Complete same-candidate native installation, upgrade, rollback and exit checks across all four targets. Retain the existing Linux ARM64 bootstrap evidence and fill the remaining native scenarios, including platform signing/notarization and compatibility requirements.
2. **Complete real-host workflows.** Retest discovery, Skill changes, authorization, approval recovery, traceability and privacy within each platform’s scope; resolve the remaining OpenClaw checkpoint, OpenShell stop and performance conditions using evidence from the same version and candidate.
3. **Develop team-device management.** Build on the existing control plane and Edge to improve device onboarding, shared authorization, offline recovery and cross-device audit, with actual environment acceptance before expanding delivery.

See the [v5 taskbook](docs/personal-experience-lan-team-next-development-taskbook-20260915-232155.md), [follow-up ledger](docs/personal-experience-closure-progress-20260913.md) and [Linux dual-host ledger](docs/linux-dual-host-progress-20260918.md).

Research priorities remain long-term archival and a DOI, independent external reproduction, new experiments with protocols defined in advance, and paper/artifact review. The personal-client 0.3.0 release does not change the research source tag, experimental denominators or conclusions; new research artifacts still need independent identity, distribution and acceptance records. Actual progress is recorded in the [operations report](docs/research/operations-20260908.md) and [task ledger](docs/open-source-research-tasks-20260908.md). Contributions follow the [DCO](DCO) and [governance rules](GOVERNANCE.md); community participation follows the [code of conduct](CODE_OF_CONDUCT.md).

## Licensing, citation and historical material

Project-owned software uses **[Apache-2.0](LICENSE)**. Explicitly listed original research documents use **[CC BY 4.0](LICENSES/README.md)**. Third-party code, patches and fonts retain their own licenses; see the [scope mapping](LICENSES/scope.json) and [third-party notices](THIRD_PARTY_NOTICES.md). Model weights and external API services are outside the project license grant.

Use **[CITATION.cff](CITATION.cff)** for the project title and author information; its version/date currently identify `research-v0.1.0-rc.1`. When citing personal-client 0.3.1, specify that release tag, source `f3d9c3f` and the actual artifact digest; experiments also need their corpus digest. See the [citation guide](docs/research/citation-guide.md).

| Community and governance | Research and archives |
| :--- | :--- |
| [Contributing](CONTRIBUTING.md) · [DCO](DCO) | [Citation guide](docs/research/citation-guide.md) · [CITATION.cff](CITATION.cff) |
| [Governance](GOVERNANCE.md) · [Code of conduct](CODE_OF_CONDUCT.md) | [Technical report](docs/research/technical-report.md) · [Reproduction](REPRODUCIBILITY.md) |
| [Private security reports](SECURITY.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) | [Competition demo](HACKATHON.md) · [V5 frozen snapshot](docs/hackathon/final-submission-state.md) |
| [Development conventions](AGENTS.md) · [Continuous integration](https://github.com/maoyadongsh/siq-agent-security/actions) | [Operations report](docs/research/operations-20260908.md) · [Task ledger](docs/open-source-research-tasks-20260908.md) |

The competition snapshot retains its original source, artifacts, video and experimental denominators. Research releases and subsequent documentation updates carry their own identity records.
