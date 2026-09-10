# site/vendor

Pinned third-party assets for the static docs site (DEV17-C / M-C2).

| File | Source | Notes |
| --- | --- | --- |
| `mermaid-11.4.1.min.js` | `npm pack mermaid@11.4.1` → `package/dist/mermaid.min.js` | Classic IIFE build; loaded by `architecture.html` without CDN. |
| `mermaid-11.4.1.min.js.sha256` | `sha256sum` of the file above | Integrity sidecar for CI (`scripts/check_site_mermaid_vendor.py`). |
| `fonts/playfair-display-latin-{500,600}-normal.woff2` | `@fontsource/playfair-display`（本仓 `apps/web` node_modules 拷贝） | 拉丁衬线标题；OFL-1.1。 |
| `fonts/dm-serif-display-latin-400-normal.woff2` | `@fontsource/dm-serif-display`（同上） | 展示数字 + `GP Digits` unicode-range 劫持；OFL-1.1。 |
| `fonts/noto-serif-sc-chinese-simplified-{400,600}-normal.woff2` | `@fontsource/noto-serif-sc`（同上） | 简体中文衬线整包，浏览器各取所需；OFL-1.1。 |

Do not restore CDN imports for Mermaid. Bump by replacing the min.js, regenerating the `.sha256` sidecar, and updating the filename/version in `architecture.html` + the check script.

字体同样不走 CDN；升级时从 `apps/web` 对应 `@fontsource/*` 包重新拷贝同名 woff2。
