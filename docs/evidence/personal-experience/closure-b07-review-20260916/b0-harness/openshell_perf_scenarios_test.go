package receipt

// O04-D frozen measurement scenarios A–E (taskbook §15.5). Only runs with
// SIQ_O04_PERF=1 and SIQ_O04_SCENARIO=<A|B|C|D|E> — never in the normal test
// suite (protocol rule: 场景测量不与全量测试并行). One test binary covers the
// native decision core and the OpenShell component paths.
//
// Evidence labeling (component vs service vs real host):
//   - A/B: in-process component fixtures with real local crypto/state files;
//     zero backend calls asserted by a counting Runner (scenario A) — evidence
//     level "component_in_process", NOT end-to-end.
//   - C: real subprocess fixture CLI (bash) answering gateway info/status —
//     "component_real_subprocess_fixture"; no gateway, no network.
//   - D: real subprocess that hangs; bounded fail-return is the measured event.
//   - E: in-process stateful fixture CLI exercising the O01/O02 policy path
//     (ReadEffective → ApplyNetwork → RollbackAuthorized with live authorizer).
//
// The Python runner scripts/personal-experience/openshell-o04-perf-protocol.py
// owns rounds, warmup, interleave order and budgets; this file only measures.

import (
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/openshell"
)

const o04ResultMarker = "SIQ_O04_RESULT="

type o04Result struct {
	Scenario string               `json:"scenario"`
	Warmup   map[string]int       `json:"warmup"`
	Samples  map[string][]float64 `json:"samples_ms"`
	Counts   map[string]int64     `json:"counts"`
	Notes    []string             `json:"notes"`
}

func o04MsSince(t0 time.Time) float64 {
	return float64(time.Since(t0).Microseconds()) / 1000.0
}

func TestO04PerfScenario(t *testing.T) {
	if os.Getenv("SIQ_O04_PERF") != "1" {
		t.Skip("explicit O04-D measurement protocol only; not part of the test suite")
	}
	scenarios := map[string]func(*testing.T) o04Result{
		"A": o04ScenarioA,
		"B": o04ScenarioB,
		"C": o04ScenarioC,
		"D": o04ScenarioD,
		// "E" removed in the B0 harness port: RollbackAuthorized does not
		// exist at b303c6f (added by O01-O03). B0 has no comparable path;
		// recorded as not_measured in the B0 runner copy.
	}
	name := os.Getenv("SIQ_O04_SCENARIO")
	run, ok := scenarios[name]
	if !ok {
		t.Fatalf("unknown SIQ_O04_SCENARIO %q (want A|B|C|D|E)", name)
	}
	res := run(t)
	res.Scenario = name
	raw, err := json.Marshal(res)
	if err != nil {
		t.Fatal(err)
	}
	t.Log(o04ResultMarker + string(raw))
}

// o04UnconfiguredClient returns a client whose environment lookup is empty and
// whose counting Runner fails the test if the CLI is ever invoked. This is the
// zero-backend-call assertion for the unconfigured native path (A01).
func o04UnconfiguredClient(t *testing.T) (*openshell.Client, *int64) {
	t.Helper()
	spawns := int64(0)
	client := openshell.New(openshell.Options{
		LookupEnv: func(string) (string, bool) { return "", false },
		LookPath:  func(string) (string, error) { return "", fs.ErrNotExist },
		Runner: func([]string) (int, string, string) {
			spawns++
			return 1, "", "unconfigured mode must not invoke any CLI"
		},
	})
	return client, &spawns
}

// Scenario A: native decision allow path (no intent enforcement) plus the
// unconfigured Diagnose path. Protocol asserts zero CLI invocations overall.
func o04ScenarioA(t *testing.T) o04Result {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	client, spawns := o04UnconfiguredClient(t)

	d := client.Diagnose()
	if d.Source != openshell.SourceNone || d.ProbeOK { // B0 harness port: B0 Diagnosis has Source/Tier, no State field
		t.Fatalf("unconfigured diagnosis wrong: %+v", d)
	}
	if *spawns != 0 {
		t.Fatalf("unconfigured Diagnose invoked CLI %d times", *spawns)
	}

	for i := 0; i < 5; i++ {
		dec, err := fx.eng.Decide(r)
		if err != nil || dec.Action != ActionAllow {
			t.Fatalf("warmup decide %d: %v %+v", i, err, dec)
		}
	}
	allow := make([]float64, 0, 200)
	for i := 0; i < 200; i++ {
		t0 := time.Now()
		dec, err := fx.eng.Decide(r)
		if err != nil || dec.Action != ActionAllow {
			t.Fatalf("decide %d: %v %+v", i, err, dec)
		}
		allow = append(allow, o04MsSince(t0))
	}
	diag := make([]float64, 0, 200)
	for i := 0; i < 200; i++ {
		t0 := time.Now()
		dd := client.Diagnose()
		if dd.Source != openshell.SourceNone {
			t.Fatalf("diagnose %d source %q", i, dd.Source)
		}
		diag = append(diag, o04MsSince(t0))
	}
	if *spawns != 0 {
		t.Fatalf("unconfigured journey made %d backend calls", *spawns)
	}
	return o04Result{
		Warmup: map[string]int{"decide_allow": 5},
		Samples: map[string][]float64{
			"decide_allow_ms":          allow,
			"diagnose_unconfigured_ms": diag,
		},
		Counts: map[string]int64{"cli_invocations_total": *spawns},
		Notes: []string{
			"unconfigured OpenShell: zero backend calls/processes across decide+diagnose (A01)",
			"component_in_process; no gateway, no network",
		},
	}
}

// Scenario B: native allow+deny under required intent enforcement — the live
// binding allow path and the revoked-binding hard deny (intent_binding_revoked).
func o04ScenarioB(t *testing.T) o04Result {
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})

	fxAllow, _, _ := revocableEngine(t, "required", "block")
	for i := 0; i < 5; i++ {
		dec, err := fxAllow.eng.Decide(r)
		if err != nil || dec.Action != ActionAllow {
			t.Fatalf("warmup allow %d: %v %+v", i, err, dec)
		}
	}
	allow := make([]float64, 0, 200)
	for i := 0; i < 200; i++ {
		t0 := time.Now()
		dec, err := fxAllow.eng.Decide(r)
		if err != nil || dec.Action != ActionAllow {
			t.Fatalf("allow %d: %v %+v", i, err, dec)
		}
		allow = append(allow, o04MsSince(t0))
	}

	fxDeny, store, binding := revocableEngine(t, "required", "block")
	if _, err := store.RevokeBinding(binding.BindingID, binding.IntentDigest); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		dec, err := fxDeny.eng.Decide(r)
		if err != nil || dec.Action != ActionDeny || dec.Receipt.ReasonCode != "intent_binding_revoked" {
			t.Fatalf("warmup deny %d: %v %+v", i, err, dec)
		}
	}
	deny := make([]float64, 0, 200)
	for i := 0; i < 200; i++ {
		t0 := time.Now()
		dec, err := fxDeny.eng.Decide(r)
		if err != nil || dec.Action != ActionDeny || dec.Receipt.ReasonCode != "intent_binding_revoked" {
			t.Fatalf("deny %d: %v %+v", i, err, dec)
		}
		deny = append(deny, o04MsSince(t0))
	}
	return o04Result{
		Warmup: map[string]int{"decide_allow_auth": 5, "decide_deny_revoked": 3},
		Samples: map[string][]float64{
			"decide_allow_auth_ms":   allow,
			"decide_deny_revoked_ms": deny,
		},
		Counts: map[string]int64{"cli_invocations_total": 0},
		Notes: []string{
			"intent enforcement required; deny via RevokeBinding hard-fail",
			"component_in_process; no gateway, no network",
		},
	}
}

// o04WriteScript writes an executable bash fixture CLI.
func o04WriteScript(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "openshell-fake")
	script := "#!/usr/bin/env bash\n" + body
	if err := os.WriteFile(path, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	return path
}

func o04EnvPairClient(bin string, probeTimeout, timeout time.Duration) *openshell.Client {
	return openshell.New(openshell.Options{
		ProbeTimeout: probeTimeout,
		Timeout:      timeout,
		PollInterval: -1,
		LookupEnv: func(k string) (string, bool) {
			switch k {
			case "SIQ_AS_OPENSHELL_CLI_BIN":
				return bin, true
			case "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT":
				return "http://127.0.0.1:18744", true
			}
			return "", false
		},
	})
}

// Scenario C: first probe (cold, includes version detection) vs repeated probe
// on a real subprocess fixture CLI. Each Probe = gateway info + status spawns.
func o04ScenarioC(t *testing.T) o04Result {
	bin := o04WriteScript(t, `
# env-pair invocation prefixes the subcommand with --gateway-endpoint <ep>
while [ "$1" = "--gateway-endpoint" ]; do shift 2; done
case "$*" in
  "gateway info")
    echo "Gateway Info"
    echo "  Gateway: siq-openshell-dev"
    echo "  Gateway endpoint: http://127.0.0.1:18744"
    echo "  Gateway version: 0.0.104"
    ;;
  "status")
    echo "Server Status"
    echo "  Gateway: siq-openshell-dev"
    echo "  Gateway version: 0.0.104"
    ;;
  *)
    echo "unexpected args: $*" >&2
    exit 1
    ;;
esac
`)
	client := o04EnvPairClient(bin, 5*time.Second, 5*time.Second)

	t0 := time.Now()
	caps, err := client.Probe()
	cold := o04MsSince(t0)
	if err != nil {
		t.Fatalf("cold probe: %v %+v", err, caps)
	}
	// B0 harness port: B0 Capabilities has no EvidenceLevel/GatewayVersion/
	// CLIVersion fields (version separation landed with O01-O03), so the B0
	// cold/repeat probe leg measures the B0 probe path without version
	// detection. Timed operation (client.Probe subprocess spawns) is identical.
	for i := 0; i < 3; i++ {
		if _, err := client.Probe(); err != nil {
			t.Fatalf("warmup probe %d: %v", i, err)
		}
	}
	repeat := make([]float64, 0, 200)
	for i := 0; i < 200; i++ {
		t0 := time.Now()
		caps, err := client.Probe()
		if err != nil {
			t.Fatalf("probe %d: %v %+v", i, err, caps)
		}
		repeat = append(repeat, o04MsSince(t0))
	}
	return o04Result{
		Warmup: map[string]int{"probe_repeat": 3},
		Samples: map[string][]float64{
			"probe_cold_ms":   {cold},
			"probe_repeat_ms": repeat,
		},
		Counts: map[string]int64{
			"cli_spawns_total":     2 + 2*3 + 2*200,
			"cli_spawns_per_probe": 2,
		},
		Notes: []string{
			"real subprocess bash fixture CLI; env-pair invocation; no gateway/network",
			"cold sample includes version detection; not pooled with repeat",
			"component_real_subprocess_fixture; NOT end-to-end service measurement",
		},
	}
}

// Scenario D: bounded fail-return when the CLI hangs. ProbeTimeout is the
// configured bound; every sample must fail (timeout) within it.
func o04ScenarioD(t *testing.T) o04Result {
	bin := o04WriteScript(t, "sleep 30\n")
	client := o04EnvPairClient(bin, 100*time.Millisecond, 100*time.Millisecond)
	for i := 0; i < 3; i++ {
		if _, err := client.Probe(); err == nil {
			t.Fatal("hung CLI must fail closed")
		}
	}
	fail := make([]float64, 0, 60)
	for i := 0; i < 60; i++ {
		t0 := time.Now()
		_, err := client.Probe()
		if err == nil {
			t.Fatalf("sample %d: hung CLI returned success", i)
		}
		fail = append(fail, o04MsSince(t0))
	}
	return o04Result{
		Warmup: map[string]int{"timeout_fail": 3},
		Samples: map[string][]float64{
			"timeout_fail_ms": fail,
		},
		Counts: map[string]int64{
			"cli_spawns_total":            3 + 60,
			"configured_timeout_bound_ms": 100,
		},
		Notes: []string{
			"fault injection: real subprocess hangs; bounded failure return is the measured event",
			"failure-return bound by design = ProbeTimeout(100ms) + min(200ms, ProbeTimeout) pipe drainage: " +
				"bash forks the hanging child, which holds inherited pipe handles after bash is killed",
			"component_real_subprocess_fault_injection; no sample excluded",
		},
	}
}

// Scenario E intentionally absent in the B0 harness port (see scenario map).
