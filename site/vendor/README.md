# site/vendor

Pinned third-party assets for the static docs site (DEV17-C / M-C2).

| File | Source | Notes |
| --- | --- | --- |
| `mermaid-11.4.1.min.js` | `npm pack mermaid@11.4.1` → `package/dist/mermaid.min.js` | Classic IIFE build; loaded by `architecture.html` without CDN. |
| `mermaid-11.4.1.min.js.sha256` | `sha256sum` of the file above | Integrity sidecar for CI (`scripts/check_site_mermaid_vendor.py`). |

Do not restore CDN imports for Mermaid. Bump by replacing the min.js, regenerating the `.sha256` sidecar, and updating the filename/version in `architecture.html` + the check script.
