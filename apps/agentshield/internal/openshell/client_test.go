package openshell

import (
	"errors"
	"os"
	"strings"
	"testing"
	"time"
)

const (
	gatewayInfo            = "Gateway Info\n  Gateway: siq-openshell-dev\n  Gateway endpoint: https://127.0.0.1:17671\n"
	gatewayInfoWithVersion = gatewayInfo + "  Gateway version: 0.0.104\n"
	versionOutputV104      = "openshell version 0.0.104\n"
	versionOutputV083      = "openshell 0.0.83\n"
	versionOutputGarbage   = "build-info: no semver here\n"
	policySetOK            = "\x1b[1m\x1b[32m✓\x1b[39m\x1b[0m Policy version 2 submitted (hash: 5385cd2cf66f)\n"
	policySetFSReject      = `Error:   × status: InvalidArgument, message: "filesystem include_workdir cannot be changed on a live sandbox"`
)

func fake(responses map[string]struct {
	rc     int
	stdout string
	stderr string
}) Runner {
	return func(args []string) (int, string, string) {
		key := strings.Join(args, "\x00")
		if r, ok := responses[key]; ok {
			return r.rc, r.stdout, r.stderr
		}
		// prefix match for policy set (tempfile path varies)
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			if r, ok := responses["policy\x00set"]; ok {
				return r.rc, r.stdout, r.stderr
			}
		}
		return 1, "", "unexpected args: " + strings.Join(args, " ")
	}
}

func k(args ...string) string { return strings.Join(args, "\x00") }

func policyOutput(revision, body string) string {
	return "Version:      " + revision + "\nStatus:       Active\nActive:       " + revision + "\nLoaded:       " + revision + " ms\n---\n" + body
}

func policyBody(t *testing.T, output string) string {
	t.Helper()
	parts := strings.SplitN(output, "---\n", 2)
	if len(parts) != 2 {
		t.Fatal("policy fixture missing marker")
	}
	return parts[1]
}

func policyFixtureDigest(t *testing.T, output string) string {
	t.Helper()
	doc, err := parsePolicyYAML(output)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := policyDigest(doc)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func backend(t *testing.T, responses map[string]struct {
	rc     int
	stdout string
	stderr string
}) *Client {
	t.Helper()
	if responses == nil {
		responses = map[string]struct {
			rc     int
			stdout string
			stderr string
		}{}
	}
	if _, ok := responses[k("status")]; !ok {
		responses[k("status")] = struct {
			rc     int
			stdout string
			stderr string
		}{0, "Server Status\n  Gateway: siq-openshell-dev\n", ""}
	}
	return New(Options{
		Runner:       fake(responses),
		EnvScript:    "/nonexistent/env.sh",
		PollInterval: -1,
	})
}

func TestReadEffectiveParsesRealOutput(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full.txt"), ""},
	})
	snap, err := c.ReadEffective("s1")
	if err != nil {
		t.Fatal(err)
	}
	if snap.Revision != "1" {
		t.Fatalf("revision %s", snap.Revision)
	}
	ro, _ := snap.Filesystem["read_only"].([]any)
	if len(ro) == 0 || ro[0] != "/usr" {
		t.Fatalf("filesystem: %v", snap.Filesystem)
	}
	if snap.Process["run_as_user"] != "sandbox" {
		t.Fatalf("process: %v", snap.Process)
	}
	if len(snap.Network) != 0 {
		t.Fatalf("network: %v", snap.Network)
	}
	if snap.EnforcementMode != "unknown" {
		t.Fatalf("mode must be unknown, got %s", snap.EnforcementMode)
	}
}

func TestProbeReportsMeasuredCapabilities(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if !caps.DynamicNetworkUpdate || !caps.StaticFilesystem || !caps.RevisionSupport {
		t.Fatalf("%+v", caps)
	}
	doc := caps.Capabilities
	if doc["network_l34"].Status != "supported" || doc["network_l34"].Semantics != "enforce" {
		t.Fatalf("network_l34: %+v", doc["network_l34"])
	}
	if doc["network_l7"].Status != "unsupported" {
		t.Fatal("network_l7 must be unsupported")
	}
	if doc["tools_mcp"].Status != "unknown" {
		t.Fatal("tools_mcp must stay unknown")
	}
	for name, item := range doc {
		if item.Basis == "" {
			t.Fatalf("%s missing basis", name)
		}
	}
}

// O04: `gateway info` text is CLI-side config; it may fill cli_version but
// never gateway_version, and schema_version stays the unknown hint.
func TestProbeSchemaVersionFromGatewayInfo(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfoWithVersion, ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if caps.CLIVersion != "0.0.104" {
		t.Fatalf("cli_version %s", caps.CLIVersion)
	}
	if caps.GatewayVersion != "unknown" {
		t.Fatalf("gateway_version must stay unknown without handshake proof, got %s", caps.GatewayVersion)
	}
	if caps.SchemaVersion != "unknown-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
	}
	if caps.EvidenceLevel != EvidenceHandshake || !caps.HandshakeVerified {
		t.Fatalf("evidence: %s %v", caps.EvidenceLevel, caps.HandshakeVerified)
	}
	if caps.MaxFilesystemPathsMeasured {
		t.Fatal("contract default must not be reported as measured")
	}
	if caps.ObservedAt == "" || caps.EndpointFingerprint != "" {
		t.Fatal("env.sh observation must be dated and non-cacheable")
	}
}

// O04: CLI version via --version also never upgrades schema_version.
func TestProbeVersionFallsBackToCLI(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
		k("--version"):       {0, versionOutputV104, ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if caps.CLIVersion != "0.0.104" {
		t.Fatalf("cli_version %s", caps.CLIVersion)
	}
	if caps.GatewayVersion != "unknown" || caps.SchemaVersion != "unknown-policy-v1" {
		t.Fatalf("gateway %s schema %s", caps.GatewayVersion, caps.SchemaVersion)
	}
}

// O04: only live handshake output (`status`) may set gateway_version, and then
// schema_version follows it.
func TestProbeGatewayVersionFromStatusHandshake(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
		k("status"):          {0, "Server Status\n  Gateway: siq-openshell-dev\n  Gateway version: 0.0.104\n", ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if caps.GatewayVersion != "0.0.104" {
		t.Fatalf("gateway_version %s", caps.GatewayVersion)
	}
	if caps.SchemaVersion != "v0.0.104-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
	}
	if caps.HandshakeGateway != "siq-openshell-dev" {
		t.Fatalf("handshake_gateway %s", caps.HandshakeGateway)
	}
}

func TestProbeUnparseableVersionIsUnknownNotInvented(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
		k("--version"):       {0, versionOutputGarbage, ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if caps.SchemaVersion != "unknown-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
	}
	if strings.Contains(caps.SchemaVersion, "0.0.") && caps.SchemaVersion != "unknown-policy-v1" {
		t.Fatal("must not invent a version")
	}
}

func TestProbeVersionCommandFailureDegradesUnknown(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
	})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if caps.SchemaVersion != "unknown-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
	}
}

func TestProbeGatewayInfoFailureIsFailClosed(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {1, "", "connection refused"},
	})
	if _, err := c.Probe(); err == nil {
		t.Fatal("expected fail-closed")
	}
}

func TestProbeRejectsForeignGateway(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {1, "", "Error: client error (Connect)\nreceived corrupt message of type InvalidContentType\n"},
	})
	_, err := c.Probe()
	if err == nil || !strings.Contains(err.Error(), "不是 OpenShell") {
		t.Fatalf("foreign gateway: %v", err)
	}
}

func TestProbeRejectsUnrecognizedSuccess(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, "{\"ok\":true,\"server\":\"openclaw\"}\n", ""},
	})
	_, err := c.Probe()
	if err == nil || !strings.Contains(err.Error(), "不是 OpenShell") {
		t.Fatalf("unrecognized success: %v", err)
	}
}

func TestProbeStatusHandshakeRejectsForeignGateway(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
		k("status"):          {1, "", "received corrupt message of type InvalidContentType"},
	})
	_, err := c.Probe()
	if err == nil || !strings.Contains(err.Error(), "不是 OpenShell") {
		t.Fatalf("status handshake: %v", err)
	}
}

// O04 acceptance item 3: status rc=0 with empty output must not upgrade
// identity, reachability or tier.
func TestProbeStatusEmptyOutputFailsClosed(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("gateway", "info"): {0, gatewayInfo, ""},
		k("status"):          {0, "", ""},
	})
	caps, err := c.Probe()
	if err == nil || !strings.Contains(err.Error(), "身份/协议未确认") {
		t.Fatalf("empty status must fail closed: %v", err)
	}
	if caps.EvidenceLevel != "" {
		t.Fatalf("no evidence may be reported: %+v", caps)
	}
	d := c.Diagnose()
	if d.State != StateIdentityUnconfirmed || d.Tier == "L3" {
		t.Fatalf("diagnosis state/tier: %+v", d)
	}
}

// O04 acceptance item 3: irrelevant rc=0 output (wrong protocol) fails closed.
func TestProbeStatusIrrelevantOutputFailsClosed(t *testing.T) {
	for _, out := range []string{"OK\n", "Server Status\n", "  Gateway: siq-openshell-dev\n", "{\"status\":\"up\"}\n"} {
		c := backend(t, map[string]struct {
			rc     int
			stdout string
			stderr string
		}{
			k("gateway", "info"): {0, gatewayInfo, ""},
			k("status"):          {0, out, ""},
		})
		if _, err := c.Probe(); err == nil || !strings.Contains(err.Error(), "身份/协议未确认") {
			t.Fatalf("irrelevant status %q must fail closed: %v", out, err)
		}
	}
}

// O04 acceptance item 4: a wrong-protocol service is reported as identity
// unconfirmed and never reaches any policy write.
func TestProbeWrongProtocolNeverWritesPolicy(t *testing.T) {
	policySetCalled := false
	c := New(Options{
		Runner: func(args []string) (int, string, string) {
			if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
				policySetCalled = true
			}
			if len(args) >= 2 && args[0] == "gateway" && args[1] == "info" {
				return 0, gatewayInfo, ""
			}
			if len(args) == 1 && args[0] == "status" {
				return 0, "Hermes agent ready\n", ""
			}
			return 1, "", "unexpected args"
		},
		EnvScript:    "/nonexistent/env.sh",
		PollInterval: -1,
	})
	// Hermes signature: foreign gateway fail-closed.
	if _, err := c.Probe(); err == nil {
		t.Fatal("foreign status must fail")
	}
	if policySetCalled {
		t.Fatal("no policy write may happen from a probe")
	}
}

// O04 acceptance item 8/9: caches are bound to the invocation fingerprint and
// expire; a changed endpoint invalidates the detected version immediately.
func TestVersionCacheBoundToEndpointAndFresh(t *testing.T) {
	env := map[string]string{
		"SIQ_AS_OPENSHELL_CLI_BIN":          "/opt/openshell",
		"SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": "https://127.0.0.1:17671",
	}
	cliVersionCalls := 0
	c := New(Options{
		LookupEnv: func(key string) (string, bool) { v, ok := env[key]; return v, ok },
		Runner: func(args []string) (int, string, string) {
			if len(args) >= 2 && args[0] == "gateway" && args[1] == "info" {
				return 0, gatewayInfo, ""
			}
			if len(args) == 1 && args[0] == "status" {
				return 0, "Server Status\n  Gateway: siq-openshell-dev\n", ""
			}
			if len(args) == 1 && args[0] == "--version" {
				cliVersionCalls++
				return 0, versionOutputV104, ""
			}
			return 1, "", "unexpected args"
		},
		PollInterval: -1,
	})
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	if cliVersionCalls != 1 {
		t.Fatalf("first probe should resolve CLI version once, got %d", cliVersionCalls)
	}
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	if cliVersionCalls != 1 {
		t.Fatalf("same-endpoint probe must reuse the cached version, got %d calls", cliVersionCalls)
	}
	env["SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"] = "https://127.0.0.1:17672"
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	if cliVersionCalls != 2 {
		t.Fatalf("endpoint change must invalidate the version cache, got %d calls", cliVersionCalls)
	}
	c.mu.Lock()
	c.detectedAt = time.Now().Add(-versionCacheTTL - time.Minute)
	c.mu.Unlock()
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	if cliVersionCalls != 3 {
		t.Fatalf("expired observation must re-resolve, got %d calls", cliVersionCalls)
	}
}

func TestLooksLikeOpenShellStatusShape(t *testing.T) {
	if !looksLikeOpenShellStatus("Server Status\n  Gateway: siq-openshell-dev\n") {
		t.Fatal("real status shape must validate")
	}
	for _, out := range []string{"", "Server Status\n", "Gateway: x\n", "Server Status\nGateway: not a valid name!!\n"} {
		if looksLikeOpenShellStatus(out) {
			t.Fatalf("%q must not validate", out)
		}
	}
	if v := parseGatewayVersion("Server Status\n  Gateway version: 0.0.104\n"); v != "0.0.104" {
		t.Fatalf("gateway version %q", v)
	}
	if v := parseGatewayVersion("Gateway Info\n  Gateway version: 0.0.104\n"); v != "0.0.104" {
		t.Fatalf("gateway version from info text: %q", v)
	}
}

func Test127001IsNotParsedAsVersion(t *testing.T) {
	if v := parseVersion(gatewayInfo); v != "" {
		t.Fatalf("loopback address must not parse as version, got %s", v)
	}
}

func TestApplyNetworkMergesStaticAndReplacesNetwork(t *testing.T) {
	var setPath string
	full := testdata(t, "policy_get_full.txt")
	active := full
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 5 && args[0] == "policy" && args[1] == "set" {
			setPath = args[4]
			raw, err := os.ReadFile(setPath)
			if err != nil {
				t.Fatal(err)
			}
			doc, err := parseYAML(string(raw))
			if err != nil {
				t.Fatal(err)
			}
			m := asMap(doc)
			fs := asMap(m["filesystem_policy"])
			ro, _ := fs["read_only"].([]any)
			if len(ro) == 0 || ro[0] != "/usr" {
				t.Fatalf("static fs lost: %v", fs)
			}
			net := asMap(m["network_policies"])
			if len(net) != 1 {
				t.Fatalf("network_policies: %v", net)
			}
			if _, ok := net["demo_allowed_api"]; ok {
				t.Fatal("must not keep caller-supplied rule names as gateway keys")
			}
			if _, err := os.Stat(setPath); err != nil {
				t.Fatal("tempfile must exist while CLI reads it")
			}
			active = policyOutput("2", string(raw))
			return 0, policySetOK, ""
		}
		if eq(args, "gateway", "info") {
			return 0, gatewayInfo, ""
		}
		return 1, "", "unexpected " + strings.Join(args, " ")
	}})
	rec, err := c.ApplyNetwork("s1", []NetworkRule{{
		Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
	}}, "1")
	if err != nil {
		t.Fatal(err)
	}
	if rec.BackendRevision != "2" || rec.Evidence["gateway_policy_hash"] != "5385cd2cf66f" || rec.AppliedPolicyDigest == "" || rec.OperationID == "" {
		t.Fatalf("%+v", rec)
	}
	if setPath == "" {
		t.Fatal("policy set not called")
	}
	if _, err := os.Stat(setPath); !os.IsNotExist(err) {
		t.Fatal("tempfile must be removed after CLI returns")
	}
}

func TestApplyNetworkTempfileCleanedOnCLIError(t *testing.T) {
	var setPath string
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setPath = args[4]
			return 1, "", "gateway rejected"
		}
		return 1, "", "unexpected"
	}})
	if _, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1"); err == nil {
		t.Fatal("expected adapter error")
	}
	if setPath == "" {
		t.Fatal("set not reached")
	}
	if _, err := os.Stat(setPath); !os.IsNotExist(err) {
		t.Fatal("tempfile must be removed on CLI error")
	}
}

func TestApplyNetworkRevisionConflict(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full.txt"), ""},
	})
	_, err := c.ApplyNetwork("s1", []NetworkRule{}, "2")
	if _, ok := err.(*RevisionConflict); !ok {
		t.Fatalf("want RevisionConflict, got %v", err)
	}
}

func TestApplyNetworkIdempotentUnchanged(t *testing.T) {
	full := testdata(t, "policy_get_full_v2.txt")
	setCalls := 0
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setCalls++
			return 0, "· Policy unchanged (version 5, hash: 12f756c6915d)\n", ""
		}
		return 1, "", "unexpected"
	}})
	rec, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}, RuleName: "siq-as-rule-0"}}, "2")
	if err != nil {
		t.Fatal(err)
	}
	if rec.BackendRevision != "2" || rec.Result != "no_op" || setCalls != 0 {
		t.Fatalf("%+v", rec)
	}
}

func TestApplyNeverCallsCreateGeneration(t *testing.T) {
	full := testdata(t, "policy_get_full.txt")
	active := full
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		joined := strings.Join(args, " ")
		if strings.Contains(joined, "create") || strings.Contains(joined, "generation") {
			t.Fatalf("create_generation must not be invoked: %v", args)
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			raw, err := os.ReadFile(args[4])
			if err != nil {
				t.Fatal(err)
			}
			active = policyOutput("2", string(raw))
			return 0, policySetOK, ""
		}
		return 1, "", "unexpected"
	}})
	if _, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1"); err != nil {
		t.Fatal(err)
	}
	if err := c.CreateGeneration("s1"); err == nil {
		t.Fatal("CreateGeneration must fail closed")
	}
}

func TestFSChangeRejectedByGateway(t *testing.T) {
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 1, policySetFSReject, ""
		}
		return 1, "", "unexpected"
	}})
	if _, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1"); err == nil {
		t.Fatal("expected adapter error")
	}
}

func TestPathLevelNetworkRuleRejected(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full.txt"), ""},
	})
	_, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443/admin", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
	if err == nil || !strings.Contains(err.Error(), "host:port") {
		t.Fatalf("%v", err)
	}
}

func TestVerifyPassIsReadbackNotEnforcement(t *testing.T) {
	full := testdata(t, "policy_get_full_v2.txt")
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, full, ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "2", AppliedPolicyDigest: policyFixtureDigest(t, full)},
		[]string{"api.example.com:443"}, []string{"10.255.255.255:1"})
	if !report.Passed || report.Level != VerifyReadback {
		t.Fatalf("%+v", report)
	}
	if report.Level == "enforcement_verified" {
		t.Fatal("must not claim enforcement_verified")
	}
	allow := report.AllowChecks[0]
	if allow.Request != "config_readback" || allow.Actual != "allow" || allow.Revision != "2" {
		t.Fatalf("%+v", allow)
	}
	if report.DenyChecks[0].Actual != "deny" {
		t.Fatalf("%+v", report.DenyChecks[0])
	}
}

func TestVerifyFailureLevelIsFailed(t *testing.T) {
	full := testdata(t, "policy_get_full_v2.txt")
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, full, ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "3", AppliedPolicyDigest: policyFixtureDigest(t, full)},
		[]string{"api.example.com:443"}, []string{"10.255.255.255:1"})
	if report.Passed || report.Level != VerifyFailed {
		t.Fatalf("%+v", report)
	}
	found := false
	for _, f := range report.Failures {
		if strings.Contains(f, "revision mismatch") {
			found = true
		}
	}
	if !found {
		t.Fatalf("missing mismatch: %v", report.Failures)
	}
}

func TestVerifyFullDigestDoesNotRequireInventedDeny(t *testing.T) {
	full := testdata(t, "policy_get_full_v2.txt")
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, full, ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "2", AppliedPolicyDigest: policyFixtureDigest(t, full)}, []string{"api.example.com:443"}, nil)
	if !report.Passed || len(report.DenyChecks) != 0 {
		t.Fatalf("full digest plus declared allow must pass without invented deny: %+v", report)
	}
}

func TestRollbackUsesTrustedSnapshotAndNonContinuousRevisions(t *testing.T) {
	base := testdata(t, "policy_get_full.txt")
	active := base
	setCalls := 0
	usedHistoryLookup := false
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			if args[3] == "--rev" {
				usedHistoryLookup = true
			}
			return 0, active, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setCalls++
			raw, err := os.ReadFile(args[4])
			if err != nil {
				t.Fatal(err)
			}
			revision := "9"
			if setCalls == 2 {
				revision = "15"
			}
			active = policyOutput(revision, string(raw))
			return 0, "✓ Policy version " + revision + " submitted (hash: 3f3f3f3f)\n", ""
		}
		return 1, "", "unexpected"
	}})
	receipt, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
	if err != nil {
		t.Fatal(err)
	}
	authorized := false
	rr, err := c.RollbackAuthorized("s1", receipt, func(request RollbackAuthorization) error {
		authorized = request.Restore.PolicyDigest == receipt.BasePolicyDigest && request.Target == "s1"
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if !authorized || rr.RestoredRevision != "15" || rr.RestoredDigest != receipt.BasePolicyDigest || rr.Result != "restored" {
		t.Fatalf("rollback=%+v authorized=%v", rr, authorized)
	}
	if usedHistoryLookup {
		t.Fatal("rollback must not calculate or fetch revision-1")
	}
	if _, err := c.RollbackAuthorized("s1", receipt, func(RollbackAuthorization) error { return nil }); err == nil {
		t.Fatal("consumed operation must reject replay")
	}
}

func TestRollbackRejectsForgedUnknownDriftedAndRevokedOperations(t *testing.T) {
	base := testdata(t, "policy_get_full.txt")
	active := base
	setCalls := 0
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setCalls++
			raw, _ := os.ReadFile(args[4])
			active = policyOutput("7", string(raw))
			return 0, "Policy version 7 submitted (hash: abcd1234)", ""
		}
		return 1, "", "unexpected"
	}})
	receipt, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
	if err != nil {
		t.Fatal(err)
	}
	forged := receipt
	forged.BasePolicyDigest = strings.Repeat("0", 64)
	if _, err := c.RollbackAuthorized("s1", forged, func(RollbackAuthorization) error { return nil }); err == nil {
		t.Fatal("forged receipt must be rejected")
	}
	if setCalls != 1 {
		t.Fatal("forged rollback must not write")
	}
	restarted := New(Options{Runner: c.Runner, PollInterval: -1, policyCoordinator: newPolicyCoordinator()})
	if _, err := restarted.RollbackAuthorized("s1", receipt, func(RollbackAuthorization) error { return nil }); err == nil {
		t.Fatal("missing registry after restart must reject")
	}
	if _, err := c.RollbackAuthorized("s1", receipt, func(RollbackAuthorization) error { return errors.New("revoked") }); err == nil {
		t.Fatal("revoked current authorization must reject")
	}
	if setCalls != 1 {
		t.Fatal("revoked rollback must not write")
	}
	active = policyOutput("8", policyBody(t, base))
	if _, err := c.RollbackAuthorized("s1", receipt, func(RollbackAuthorization) error { return nil }); err == nil {
		t.Fatal("external drift must reject")
	}
	if setCalls != 1 {
		t.Fatal("drifted rollback must not write")
	}
}

func TestRollbackNoOpIsZeroWrite(t *testing.T) {
	active := testdata(t, "policy_get_full_v2.txt")
	setCalls := 0
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setCalls++
			return 1, "", "must not write"
		}
		return 1, "", "unexpected"
	}})
	receipt, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}, RuleName: "siq-as-rule-0"}}, "2")
	if err != nil || receipt.Result != "no_op" {
		t.Fatalf("receipt=%+v err=%v", receipt, err)
	}
	rollback, err := c.Rollback("s1", receipt)
	if err != nil || rollback.Result != "no_op" || setCalls != 0 {
		t.Fatalf("rollback=%+v err=%v writes=%d", rollback, err, setCalls)
	}
}

func TestSandboxListDockerFallbackBelowV104(t *testing.T) {
	c := New(Options{
		EnvScript: "/nonexistent/env.sh", PollInterval: -1,
		Runner: func(args []string) (int, string, string) {
			if eq(args, "gateway", "info") {
				return 0, gatewayInfo, ""
			}
			if eq(args, "status") {
				return 0, "Server Status\n  Gateway: siq-openshell-dev\n", ""
			}
			if eq(args, "--version") {
				return 0, versionOutputV083, ""
			}
			if len(args) >= 2 && args[0] == "sandbox" && args[1] == "list" {
				return 1, "", "status: Internal, message: failed to decode Protobuf message: Sandbox.id"
			}
			return 1, "", "unexpected"
		},
		DockerRunner: func(args []string) (int, string, string) {
			return 0, "openshell-siq-as-live-8515c645-1682-4814-965d-e6b330e2af2e\n", ""
		},
	})
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	page, err := c.ListTargets()
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Targets) != 1 || page.Targets[0]["id"] != "siq-as-live" {
		t.Fatalf("%v", page.Targets)
	}
}

func TestSandboxListV104RetiresDockerFallback(t *testing.T) {
	dockerCalls := 0
	c := New(Options{
		EnvScript: "/nonexistent/env.sh", PollInterval: -1,
		Runner: func(args []string) (int, string, string) {
			if eq(args, "gateway", "info") {
				return 0, gatewayInfoWithVersion, ""
			}
			if eq(args, "status") {
				return 0, "Server Status\n  Gateway: siq-openshell-dev\n", ""
			}
			if len(args) >= 2 && args[0] == "sandbox" && args[1] == "list" {
				return 1, "", "status: Internal, message: some real error"
			}
			return 1, "", "unexpected"
		},
		DockerRunner: func(args []string) (int, string, string) {
			dockerCalls++
			return 0, "openshell-siq-as-live-8515c645-1682-4814-965d-e6b330e2af2e\n", ""
		},
	})
	if _, err := c.Probe(); err != nil {
		t.Fatal(err)
	}
	if _, err := c.ListTargets(); err == nil || err.Error() != errCommandFailed {
		t.Fatalf("%v", err)
	}
	if dockerCalls != 0 {
		t.Fatal("docker fallback must be retired at v0.0.104")
	}
}

func TestStreamEventsLabelsSource(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "list"): {0, "siq-as-live  version 2\n", ""},
	})
	batch := c.StreamEvents("")
	if batch.Source != "cli_policy_list_readback" || batch.Events[0]["type"] != "policy_history" {
		t.Fatalf("%+v", batch)
	}
	failing := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "list"): {1, "", "connection refused"},
	})
	batch2 := failing.StreamEvents("c1")
	if batch2.Events[0]["type"] != "backend_unavailable" || batch2.Source != "cli_policy_list_readback" {
		t.Fatalf("%+v", batch2)
	}
}

func TestCLIFailureIsFailClosed(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "x", "--full"): {1, "", "boom"},
	})
	if _, err := c.ReadEffective("x"); err == nil {
		t.Fatal("expected fail-closed")
	}
}

func eq(args []string, want ...string) bool {
	if len(args) != len(want) {
		return false
	}
	for i := range args {
		if args[i] != want[i] {
			return false
		}
	}
	return true
}
