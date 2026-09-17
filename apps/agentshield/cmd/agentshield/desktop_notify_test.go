package main

import (
	"errors"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/notify"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestDesktopNotifierConfiguredCommandWins(t *testing.T) {
	n := desktopNotifier(state.Config{DesktopNotifyCommand: " my-notify  -u critical "})
	cn, ok := n.(notify.CommandNotifier)
	if !ok {
		t.Fatalf("expected CommandNotifier, got %T", n)
	}
	if cn.Bin != "my-notify" || len(cn.Args) != 2 || cn.Args[0] != "-u" || cn.Args[1] != "critical" {
		t.Fatalf("argv must be whitespace-split without a shell: %+v", cn)
	}
}

func TestDesktopNotifierUnsupportedPlatformWithoutOverrideStaysSilent(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	// On a platform whose DefaultCommand reports false and with no configured
	// override, the honest result is nil (no notifier), never a fake one.
	if argv, ok := notify.DefaultCommand(runtime.GOOS); ok && len(argv) > 0 {
		t.Skipf("platform %s has a default notifier; nil contract only applies where none exists", runtime.GOOS)
	}
	if n := desktopNotifier(state.Config{}); n != nil {
		t.Fatalf("unsupported platform must yield nil notifier, got %T", n)
	}
}

func TestStartDesktopNotifyDisabledAndUnsupportedAreNoOps(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	var lines []string
	logf := func(format string, args ...any) { lines = append(lines, strings.TrimSpace(format)) }
	if cancel := startDesktopNotify(state.Config{}, nil, logf); cancel != nil {
		cancel()
		t.Fatal("default config (off) must not start the dispatcher")
	}
	if _, ok := notify.DefaultCommand(runtime.GOOS); ok {
		t.Skipf("platform %s has a default notifier; the unsupported-platform no-op only applies where none exists", runtime.GOOS)
	}
	cancel := startDesktopNotify(state.Config{DesktopNotify: true}, nil, logf)
	if cancel != nil {
		cancel()
		t.Fatal("unsupported platform must not start the dispatcher")
	}
	joined := strings.Join(lines, "\n")
	if !strings.Contains(joined, "no notifier available") || !strings.Contains(joined, "inbox remains fully usable") {
		t.Fatalf("startup log must state honestly that nothing was started: %q", joined)
	}
}

// On darwin the honest default exists: desktopNotifier resolves osascript and
// the dispatcher starts for real when opted in.
func TestDesktopNotifierDarwinDefaultResolves(t *testing.T) {
	if runtime.GOOS != "darwin" {
		t.Skip("darwin-only contract")
	}
	n := desktopNotifier(state.Config{})
	cn, ok := n.(notify.CommandNotifier)
	if !ok || cn.Bin != "/usr/bin/osascript" {
		t.Fatalf("darwin default must resolve osascript, got %T %+v", n, n)
	}
}

func testDeployedGrant(t *testing.T, k *signing.Key) *grant.Grant {
	t.Helper()
	f := func(domain, action, rtype, value string) admission.DeclaredFact {
		return admission.DeclaredFact{Domain: domain, Action: action,
			Resource: admission.Resource{Type: rtype, Value: value},
			Effect:   "allow", State: "declared", Authority: "skill_manifest",
			SourceField: "t", EvidenceIDs: []string{"ev-1"}}
	}
	adm := admission.Admission{AdmissionID: "adm-notify", ContentHash: strings.Repeat("a", 64),
		Verdict: "admit_with_conditions", EvidenceIDs: []string{"ev-1"},
		DeclaredFacts: []admission.DeclaredFact{
			f("tool", "tool.invoke", "tool", "exec"),
			// A credential fact makes exec require per-use approval, so the
			// engine actually holds the call below.
			f("credential", "credential.read", "credential_ref", ".env"),
		}}
	res, err := grant.Build(adm, grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "inst_1"},
		Platform: "openclaw", Key: k})
	if err != nil {
		t.Fatal(err)
	}
	g, err := grant.Approve(res.Grant, grant.Approval{ActorType: "human", ActorID: "u", ApprovedAt: "2026-09-04T06:00:00Z"}, k)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, k)
	if err != nil {
		t.Fatal(err)
	}
	return &g
}

func TestPendingConfirmationsCountsOnlyPending(t *testing.T) {
	k, err := signing.Load(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(t.TempDir(), "local", k)
	if err != nil {
		t.Fatal(err)
	}
	g := testDeployedGrant(t, k)
	eng, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, EnforcementMode: "block",
		Version: "test", HoldChannel: "console",
		Grants: func(p, a string) *grant.Grant {
			if p == g.Platform && a == "inst_1" {
				return g
			}
			return nil
		}})
	if err != nil {
		t.Fatal(err)
	}
	d, err := eng.Decide(receipt.Request{Platform: "openclaw", SessionID: "sess-1", AgentID: "inst_1",
		Tool: "exec", ToolCallID: "tc-1", Params: map[string]any{"command": "printf hi"},
		Context: map[string]any{"cwd": "/home/u/proj"}})
	if err != nil || d.Action != receipt.ActionHold {
		t.Fatalf("expected a held action: %v %+v", err, d)
	}
	if got := pendingConfirmations(eng)(); got != 1 {
		t.Fatalf("want 1 pending, got %d", got)
	}
	list := eng.Confirmations()
	if len(list.Items) != 1 {
		t.Fatalf("want 1 confirmation item, got %d", len(list.Items))
	}
	if _, err := eng.ResolveConfirmation(list.Items[0].ActionID, receipt.ConfirmationResolve{
		SchemaVersion: "local-confirmation-resolve/v1", DecisionReceiptID: d.Receipt.ReceiptID,
		DecisionHash: d.Receipt.Hash, ParamsDigest: d.Receipt.ParamsDigest, Approve: true, ActorID: "reviewer",
	}); err != nil {
		t.Fatal(err)
	}
	if got := pendingConfirmations(eng)(); got != 0 {
		t.Fatalf("resolved hold must stop counting, got %d", got)
	}
}

func TestDesktopNotifyConfigValidation(t *testing.T) {
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	// SaveConfig is a plain write (config.json holds no security decisions);
	// validation happens on load. Start from the documented defaults so other
	// required fields stay valid.
	base, err := st.LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	bad := base
	bad.DesktopNotifyCommand = "   "
	if err := st.SaveConfig(bad); err != nil {
		t.Fatal(err)
	}
	if _, err := st.LoadConfig(); err == nil {
		t.Fatal("whitespace-only command must be rejected on load")
	}
	good := base
	good.DesktopNotify = true
	good.DesktopNotifyCommand = "notify-send -u normal"
	if err := st.SaveConfig(good); err != nil {
		t.Fatalf("valid command must be accepted: %v", err)
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.DesktopNotify || cfg.DesktopNotifyCommand != "notify-send -u normal" {
		t.Fatalf("round-trip failed: %+v", cfg)
	}
}

func TestDispatcherPendingCountBindsDeliveryErrorToLog(t *testing.T) {
	// Sanity: dispatcher wired with a failing notifier logs through the serve
	// log channel and never panics — the property startDesktopNotify relies on.
	st := &failingNotifier{}
	var logged []string
	d := notify.NewDispatcher(func() int { return 3 }, st, notify.DispatcherOptions{
		PollInterval:     time.Second,
		CoalesceInterval: 15 * time.Second,
		Log:              func(e error) { logged = append(logged, e.Error()) },
	})
	if d.Tick(time.Date(2026, 9, 13, 8, 0, 0, 0, time.UTC)) {
		t.Fatal("failed delivery must not report success")
	}
	if len(logged) != 1 || !strings.Contains(logged[0], "delivery failed") {
		t.Fatalf("failure must reach the log channel: %v", logged)
	}
}

type failingNotifier struct{}

func (failingNotifier) Notify(notify.Notification) error { return errors.New("delivery failed") }
