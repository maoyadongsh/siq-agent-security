package openshell

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestO05LiveCrossBoundaryEnforcement is the corrected opt-in behavioral
// enforcement test for the O05 network path, rebuilt from the 2026-09-16 L01
// root-cause findings (docs/evidence/.../l01-root-cause.md):
//
//   - Sandbox loopback (127.0.0.1) traffic sits outside the enforcement
//     boundary and must never be used to claim blocking success. This test
//     therefore makes loopback claims of no kind.
//   - Cross-boundary egress is default-deny through the sandbox egress proxy;
//     an allow rule in the agentshield wire shape (host:port + binary path)
//     lets matching traffic reach a controlled receiver, and non-matching
//     traffic is rejected before arrival.
//   - A blocking claim requires a positive control: traffic to a test-owned
//     receiver on the SAME egress path must be proven to arrive before any
//     "violating target blocked" assertion is trusted.
//
// Opt-in and destructive only to policy state, which is restored on both the
// success path and best-effort cleanup after a failed assertion (same
// discipline as TestOpenShellLivePolicyFidelityAndRollback). The test never
// creates or deletes a sandbox.
//
// Required env:
//
//	SIQ_O05_ENFORCE_LIVE=1
//	SIQ_O05_ENFORCE_TARGET         sandbox name
//	SIQ_O05_ENFORCE_CONFIRM_TARGET must equal SIQ_O05_ENFORCE_TARGET
//	SIQ_AS_OPENSHELL_ENV_SH        CLI environment script
//	SIQ_O05_ENFORCE_EGRESS_HOST    host IP reachable cross-boundary from the
//	                               sandbox (e.g. the docker bridge gateway);
//	                               must not be a loopback address
//
// Optional env:
//
//	SIQ_O05_ENFORCE_BIND           host bind address for the receivers
//	                               (default 0.0.0.0:0, two free ports; the
//	                               sandbox reaches the host over the bridge
//	                               gateway IP, so a loopback-only bind is
//	                               unreachable cross-boundary)
//	SIQ_O05_ENFORCE_BIN            sandbox binary allowed by the rule
//	                               (default /usr/local/bin/python3)
func TestO05LiveCrossBoundaryEnforcement(t *testing.T) {
	if os.Getenv("SIQ_O05_ENFORCE_LIVE") != "1" {
		t.Skip("explicit live opt-in required")
	}
	target := os.Getenv("SIQ_O05_ENFORCE_TARGET")
	if target == "" || os.Getenv("SIQ_O05_ENFORCE_CONFIRM_TARGET") != target {
		t.Fatal("SIQ_O05_ENFORCE_TARGET must be set and matched by SIQ_O05_ENFORCE_CONFIRM_TARGET")
	}
	envScript := os.Getenv("SIQ_AS_OPENSHELL_ENV_SH")
	if envScript == "" {
		t.Fatal("SIQ_AS_OPENSHELL_ENV_SH is required")
	}
	egressHost := os.Getenv("SIQ_O05_ENFORCE_EGRESS_HOST")
	if net.ParseIP(egressHost) == nil || net.ParseIP(egressHost).IsUnspecified() || isLoopbackHost(egressHost) {
		t.Fatal("SIQ_O05_ENFORCE_EGRESS_HOST must be a cross-boundary address, not loopback: loopback traffic bypasses enforcement (L01 root cause)")
	}
	bin := os.Getenv("SIQ_O05_ENFORCE_BIN")
	if bin == "" {
		bin = "/usr/local/bin/python3"
	}
	bind := os.Getenv("SIQ_O05_ENFORCE_BIND")
	if bind == "" {
		bind = "0.0.0.0:0"
	}

	// Two test-owned correlation-ID receivers: allowPort is the positive
	// control target; denyPort is the violating target whose log must stay
	// empty. Both live on the same host path, so a dead receiver can never be
	// mistaken for a block.
	allowSrv, allowPort := startReceiver(t, bind)
	denySrv, denyPort := startReceiver(t, bind)

	client := New(Options{
		EnvScript:         envScript,
		Timeout:           60 * time.Second,
		PollInterval:      100 * time.Millisecond,
		PollAttempts:      30,
		MaxOutput:         2 << 20,
		policyCoordinator: newPolicyCoordinator(),
	})
	if _, err := client.Probe(); err != nil {
		t.Fatalf("live OpenShell probe failed: %v", err)
	}
	base, err := client.ReadEffective(target)
	if err != nil {
		t.Fatalf("read live base policy: %v", err)
	}
	var pending *DeploymentReceipt
	var restoreBase Snapshot
	restore := func() error {
		if pending == nil {
			return nil
		}
		if err := restoreEnforcementPolicy(client, target, *pending, restoreBase); err != nil {
			return err
		}
		pending = nil
		return nil
	}
	t.Cleanup(func() {
		if err := restore(); err != nil {
			t.Errorf("owned policy cleanup refused; inspect target: %v", err)
		}
	})
	apply := func(rules []NetworkRule) {
		before, err := client.ReadEffective(target)
		if err != nil {
			t.Fatal(err)
		}
		rec, err := client.ApplyNetwork(target, rules, before.Revision)
		if err != nil {
			t.Fatalf("apply incomplete; inspect owned target; no force restore: %v", err)
		}
		pending = &rec
		restoreBase = before
	}
	corr := fmt.Sprintf("siq-o05-enf-%d", time.Now().UnixNano())

	allowEndpoint := net.JoinHostPort(egressHost, fmt.Sprint(allowPort))
	denyEndpoint := net.JoinHostPort(egressHost, fmt.Sprint(denyPort))
	rule := func(ep string) NetworkRule {
		return NetworkRule{Endpoint: ep, Effect: "allow", BinaryPaths: []string{bin}}
	}
	// Prove BOTH exact destinations are reachable before tightening policy.
	apply([]NetworkRule{rule(allowEndpoint), rule(denyEndpoint)})
	waitAllowed := func(endpoint, id string, receiver *receiver) {
		start := time.Now()
		deadline := start.Add(30 * time.Second)
		for {
			outcome := execSandboxFetch(t, client, target, bin, "http://"+endpoint+"/?corr_id="+id)
			if outcome == fetchArrived {
				break
			}
			if outcome != fetchBlocked {
				t.Fatalf("unknown fetch outcome; cannot claim policy behavior: %s", outcome)
			}
			if time.Now().After(deadline) {
				t.Fatal("allow propagation deadline exceeded")
			}
			time.Sleep(time.Second)
		}
		if receiver.arrivals(id) != 1 {
			t.Fatal("positive control arrival not proven")
		}
		t.Logf("allow propagation_ms=%d", time.Since(start).Milliseconds())
	}
	waitAllowed(allowEndpoint, corr+"-positive-allow", allowSrv)
	waitAllowed(denyEndpoint, corr+"-positive-deny", denySrv)
	if err := restore(); err != nil {
		t.Fatalf("positive control restore: %v", err)
	}
	apply([]NetworkRule{rule(allowEndpoint)})
	applied := *pending
	report := client.Verify(target, applied, []string{allowEndpoint}, []string{denyEndpoint})
	if !report.Passed {
		t.Fatalf("readback verification failed: %+v", report)
	}
	waitAllowed(allowEndpoint, corr+"-allow", allowSrv)
	denyArrived := execSandboxFetch(t, client, target, bin, "http://"+denyEndpoint+"/?corr_id="+corr+"-deny")
	t.Logf("deny_probe outcome=%s arrivals=%d", denyArrived, denySrv.arrivals(corr+"-deny"))
	if err := requireEnforcementDenied(denyArrived, denySrv.arrivals(corr+"-deny")); err != nil {
		t.Fatal(err)
	}
	if err := restore(); err != nil {
		t.Fatalf("final restore: %v", err)
	}
	final, err := client.ReadEffective(target)
	if err != nil || final.PolicyDigest != base.PolicyDigest {
		t.Fatal("original policy not restored")
	}
	// Loopback accounting: per the L01 matrix, sandbox loopback traffic is
	// outside the enforcement boundary. This test records no loopback
	// pass/fail and derives no blocking claim from loopback behavior.
	t.Logf("cross-boundary enforcement pass target=%s allowed=%s (arrived) violating=%s:%d (blocked, 0 arrivals) both_targets_reachable=ok restore_verified=true base_revision=%s applied_revision=%s",
		target, allowEndpoint, egressHost, denyPort, base.Revision, applied.BackendRevision)
}

const (
	fetchArrived = "arrived"
	fetchBlocked = "http_403"
	fetchUnknown = "unknown"
)

// execSandboxFetch runs a short-lived urllib fetch inside the sandbox and
// classifies the outcome from the fetch report only; arrival truth is always
// cross-checked against the receiver's own correlation-ID log by the caller.
func execSandboxFetch(t *testing.T, client *Client, target, bin, url string) string {
	t.Helper()
	code := "import urllib.request,urllib.error,json\n" +
		"try:\n    r=urllib.request.urlopen(" + pyStr(url) + ",timeout=10)\n    print(json.dumps({'status':r.status}))\n" +
		"except urllib.error.HTTPError as e:\n    print(json.dumps({'status':e.code}))\n" +
		"except Exception:\n    print(json.dumps({'error':'transport_failure'}))\n"
	// cli() joins stderr diagnostics to stdout for human-readable commands.
	// This probe has a JSON stdout protocol: keep the channels separate while
	// retaining the bounded runner and nonzero-exit/output-limit refusal.
	rc, out, diagnostic := client.Runner([]string{"sandbox", "exec", "-n", target, "--", bin, "-c", code})
	if rc != 0 || len(out) > client.MaxOutput || len(diagnostic) > client.MaxOutput-len(out) {
		return fetchUnknown
	}
	return classifyEnforcementFetch(out, nil)

}

func pyStr(s string) string { b, _ := json.Marshal(s); return string(b) }

func classifyEnforcementFetch(out string, transportErr error) string {
	if transportErr != nil {
		return fetchUnknown
	}
	var response struct {
		Status int    `json:"status"`
		Error  string `json:"error"`
	}
	dec := json.NewDecoder(strings.NewReader(out))
	dec.DisallowUnknownFields()
	if dec.Decode(&response) != nil || response.Error != "" {
		return fetchUnknown
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		return fetchUnknown
	}
	if response.Status == 403 {
		return fetchBlocked
	}
	if response.Status >= 200 && response.Status < 300 {
		return fetchArrived
	}
	return fetchUnknown
}
func requireEnforcementDenied(outcome string, arrivals int) error {
	if outcome != fetchBlocked || arrivals != 0 {
		return errors.New("policy denial not proven: need explicit HTTP 403 and zero arrivals")
	}
	return nil
}
func restoreEnforcementPolicy(c *Client, target string, rec DeploymentReceipt, base Snapshot) error {
	rb, err := c.RollbackAuthorized(target, rec, func(a RollbackAuthorization) error {
		if a.Target != target || a.OperationID != rec.OperationID || a.Restore.PolicyDigest != base.PolicyDigest {
			return errors.New("restore binding mismatch")
		}
		return nil
	})
	if err != nil {
		return err
	}
	after, err := c.ReadEffective(target)
	if err != nil {
		return err
	}
	if after.PolicyDigest != base.PolicyDigest || after.Revision != rb.RestoredRevision {
		return errors.New("restore readback mismatch")
	}
	return nil
}

// receiver is a test-owned HTTP receiver that records every request by
// correlation ID so arrival is proven by the receiver itself, never inferred
// from the client-side result.
type receiver struct {
	srv *http.Server
	mu  sync.Mutex
	ids map[string]int
}

func (r *receiver) arrivals(corrID string) int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.ids[corrID]
}

func startReceiver(t *testing.T, bind string) (*receiver, int) {
	t.Helper()
	ln, err := net.Listen("tcp", bind)
	if err != nil {
		t.Fatalf("bind test receiver on %s: %v", bind, err)
	}
	r := &receiver{ids: map[string]int{}}
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, req *http.Request) {
		id := req.URL.Query().Get("corr_id")
		r.mu.Lock()
		r.ids[id]++
		r.mu.Unlock()
		w.WriteHeader(http.StatusOK)
	})
	r.srv = &http.Server{Handler: mux, ReadHeaderTimeout: 10 * time.Second}
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = r.srv.Serve(ln)
	}()
	t.Cleanup(func() {
		_ = r.srv.Close()
		<-done
	})
	return r, ln.Addr().(*net.TCPAddr).Port
}
