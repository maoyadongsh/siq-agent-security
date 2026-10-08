# Desired policy update semantics v1

This supplements DesiredPolicy v1 and OpenShell policy safety v2. It describes
compiler inputs and planning, not a new backend permission or generation API.
Existing signed artifacts and historical vectors are unchanged.

| Input | Meaning |
| --- | --- |
| Domain omitted | No intent for that domain; retain live backend state. |
| Domain null in API/DB/compiler compatibility input | Same as omitted; never deletion. The exported DesiredPolicy schema still omits absent domains. |
| `filesystem: {}` | Explicitly replace both represented path lists with empty lists. |
| filesystem with one represented list omitted | Omitted list defaults to empty; these two lists are a replacement pair, not a per-path union. |
| filesystem list `[]` or shorter list | Clear or narrow that list. Compare exact values before planning. |
| filesystem list null, scalar, or non-string element | Reject; do not convert invalid values to empty lists. |
| Unknown desired filesystem field | Reject before mutation; never discard intent. Live backend extensions are preserved separately. |
| `process: {}` | Empty field patch; preserve live process state, including absent section. |
| Nonempty process object | Explicit field patch; omitted fields remain. A present null is a value, not field deletion, and differs from an absent live field. |
| `network: []` | Explicit replacement with no allowed endpoints; must remain in the compiled artifact. |
| Empty list supplied instead of filesystem/process object | Reject. |
| Explicit field/domain deletion | Not supported by this v1 interface. Null and omission cannot request it; use an explicitly supported generation workflow when available. |

Any represented static change requires generation. A backend without generation
must refuse it; a network write cannot silently report successful application of
changed filesystem/process intent. Identical supplied static fields and an empty
process patch need no generation. Network-only writes clone the complete current
policy and preserve static sections, including unknown backend extensions.

Python and Go compilers consume the additional shared
`fixtures/policy_update_semantics_v1.json` vectors. Empty static objects and empty
network arrays retain their explicit intent and canonical artifact identity.
This tightens invalid filesystem input handling; clients relying on ignored
filesystem keys must remove them or use a separately supported capability.

The local administrator endpoint `POST /v1/openshell/apply` is a network
replacement command, not a DesiredPolicy patch. It requires an explicit
non-null `network` array; `[]` is intentional clearance, while missing/null
is rejected before backend access. Unknown static fields are rejected by its
strict request decoder. The CLI `openshell apply` requires explicit `--allow`
and `--binary` arguments and does not expose static generation or implicit
clearance. Neither local entry claims the enterprise approval workflow.
