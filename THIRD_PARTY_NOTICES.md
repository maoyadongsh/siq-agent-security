# Third-party notices

The root Apache-2.0 grant applies to project-owned work. It does not replace these upstream licenses or claim their authors' endorsement.

| Material | Attribution and license | Inventory |
| --- | --- | --- |
| OpenClaw 2026.5.12 candidate patches | Peter Steinberger and contributors; [upstream MIT](patches/openclaw/LICENSE). Local modifications are marked in patch metadata and README. | [Source inventory](docs/research/third-party-source-inventory.json) |
| Mermaid 11.4.1 static bundle | [Mermaid MIT license](site/vendor/mermaid-LICENSE); original bundle bytes preserved, export alias appended. | Same source inventory, including 70 source-map component versions |
| Mermaid bundled components | Original notices remain in the JS; [extracted notices](site/vendor/mermaid-bundled-notices.txt) plus per-component license/notice copies below. | [LICENSES/third-party](LICENSES/third-party) |
| Web runtime dependencies and fonts | React and router packages retain upstream licenses; four Fontsource font families retain OFL-1.1 and font names/attribution. | [Dependency inventory](docs/research/third-party-dependency-inventory.json), license files under LICENSES/third-party |
| Python Control API dependencies | Installed separately from uv.lock; package-specific metadata/terms apply. | Dependency inventory includes all locked runtime and development packages |
| Go runtime/toolchain | Project modules use the standard library and local module references. Redistributed Go binaries require the Go license as well. | [Go license](LICENSES/Go-BSD-3-Clause.txt) |

The Mermaid inventory is derived from the exact npm 11.4.1 distribution source map, not just its top-level dependency list. Original package license and notice files were obtained from each pinned npm archive; archive hashes and license-file paths are recorded. Preserve those notices when serving or redistributing the vendored JS. DOMPurify's alternative license choices remain upstream terms; it is not relicensed by this repository.

Web development dependencies are included in the lock inventory even when not intentionally redistributed in a runtime bundle. A new binary distribution must inspect its actual emitted files, helper code, fonts and dependencies rather than claiming this inventory is a complete binary SBOM. Installed Python wheels and container base images are outside the current source distribution; redistributing them requires their own notices. Model weights and external provider services are not covered by project licenses.

License texts under LICENSES/third-party, the DCO text, and the standard license texts retain their original terms. The license source URLs and evidence limitations are in [license review](docs/research/license-review.md).
