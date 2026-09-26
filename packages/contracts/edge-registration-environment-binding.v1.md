# Initial registration expected-environment extension

Additive optional `expected_environment_id` on POST /edge/v1/register, an ASCII
identifier 1..64 characters. Omitted/null is legacy behavior; enterprise installer
must send the confirmed plan's environment. Before consuming the enrollment code
or creating a device, compare the token's server-owned environment. Mismatch is
401 enrollment_invalid, with no device, used_at change or registration audit.
This expectation never determines tenant ownership or grants business rights.

Edge `register --environment ID` persists this expectation in its private pending
journal before sending, transmits it, and rejects a response for another
environment. Registration recovery requires the same saved expected environment
when present. Older pending journals without the field remain readable.
Bound registration to old servers may be rejected as an unknown field; never
silently retry without the expectation. New servers remain compatible with old
clients, but legacy omission must not be labeled installation-plan binding.
