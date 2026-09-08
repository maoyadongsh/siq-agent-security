# Reproduction environment matrix

| Track | Actual environment / result | Scope |
| --- | --- | --- |
| A fixture UI | Linux aarch64 on the existing DGX host, explicit test provider; all nine browser scenarios passed | CPU/test path, no model call or GPU requirement; hosted ordinary Ubuntu CI also passed all nine scenarios; see reproduction-a/hosted-linux-identity.json |
| B fixed controls | Same host, Go 1.26.6; 23/23 expectations, 318 receipt signatures and 20 effect envelopes verified | Fixed synthetic corpus; dirty development source, component digests recorded |
| C actual models | Not rerun in this research cycle | V5 source has historical actual StepFun/Ornith and locality evidence; no new paid run or research model claim |

The same physical DGX host executing CPU fixtures does not establish independent non-DGX reproduction. CI run 34241801688 on hosted Ubuntu supplies additional Linux evidence; it does not retroactively make the local UI test an x86 result. Four-platform cross compilation is not native testing of all platforms.

See reproduction-b/identity.json under evidence for exact source/runner/verifier/binary hashes and tools. Browser summary is in evidence/reproduction-a/browser.json; screenshots remain private because pairing information may appear. Diagnostic steps and state ownership are in REPRODUCIBILITY.md.
