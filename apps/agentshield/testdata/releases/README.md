# Historical signed release fixtures

`siq-agent-security-v0.2.0/` contains 28 tracked files copied byte for byte from `0c1817c1150fd8051998c3292a6659925684ad5d:skills/siq-agent-security/`. The signed manifest and embedded publisher public key are unchanged. This is a verification fixture, not a current installation package; it intentionally preserves historical verifier behavior. Do not install it to obtain current Windows fixes.

Mutable source is `skills/siq-agent-security/`. Official signature/content verification uses this fixture. Current-source bootstrap tests sign only temporary copies with test keys and also check rejection of unsigned source. Future releases require fresh publisher signing of staged source and binaries; these historical artifact hashes do not authorize current builds.
