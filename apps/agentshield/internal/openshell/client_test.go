package openshell

import (
	"os"
	"strings"
	"testing"
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

func backend(t *testing.T, responses map[string]struct {
	rc     int
	stdout string
	stderr string
}) *Client {
	t.Helper()
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
	if caps.SchemaVersion != "v0.0.104-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
	}
}

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
	if caps.SchemaVersion != "v0.0.104-policy-v1" {
		t.Fatalf("schema %s", caps.SchemaVersion)
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

func Test127001IsNotParsedAsVersion(t *testing.T) {
	if v := parseVersion(gatewayInfo); v != "" {
		t.Fatalf("loopback address must not parse as version, got %s", v)
	}
}

func TestApplyNetworkMergesStaticAndReplacesNetwork(t *testing.T) {
	var setPath string
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
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
	if rec.BackendRevision != "2" || rec.Evidence["snapshot_hash"] != "5385cd2cf66f" {
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
	if _, err := c.ApplyNetwork("s1", nil, "1"); err == nil {
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
	_, err := c.ApplyNetwork("s1", nil, "0")
	if _, ok := err.(*RevisionConflict); !ok {
		t.Fatalf("want RevisionConflict, got %v", err)
	}
}

func TestApplyNetworkIdempotentUnchanged(t *testing.T) {
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 0, "· Policy unchanged (version 5, hash: 12f756c6915d)\n", ""
		}
		return 1, "", "unexpected"
	}})
	rec, err := c.ApplyNetwork("s1", nil, "1")
	if err != nil {
		t.Fatal(err)
	}
	if rec.BackendRevision != "5" || rec.Evidence["snapshot_hash"] != "12f756c6915d" {
		t.Fatalf("%+v", rec)
	}
}

func TestApplyNeverCallsCreateGeneration(t *testing.T) {
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		joined := strings.Join(args, " ")
		if strings.Contains(joined, "create") || strings.Contains(joined, "generation") {
			t.Fatalf("create_generation must not be invoked: %v", args)
		}
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 0, policySetOK, ""
		}
		return 1, "", "unexpected"
	}})
	if _, err := c.ApplyNetwork("s1", nil, "1"); err != nil {
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
	if _, err := c.ApplyNetwork("s1", nil, "1"); err == nil {
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
	_, err := c.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443/admin"}}, "1")
	if err == nil || !strings.Contains(err.Error(), "path") {
		t.Fatalf("%v", err)
	}
}

func TestVerifyPassIsReadbackNotEnforcement(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full_v2.txt"), ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "2"},
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
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full_v2.txt"), ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "3"},
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

func TestVerifyRequiresBothAllowAndDeny(t *testing.T) {
	c := backend(t, map[string]struct {
		rc     int
		stdout string
		stderr string
	}{
		k("policy", "get", "s1", "--full"): {0, testdata(t, "policy_get_full_v2.txt"), ""},
	})
	report := c.Verify("s1", DeploymentReceipt{BackendRevision: "2"}, []string{"api.example.com:443"}, nil)
	if report.Passed {
		t.Fatal("one-sided verify must fail")
	}
}

func TestRollbackUsesGatewayRevisionAndCleansTempfile(t *testing.T) {
	var setPath string
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 2 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			setPath = args[4]
			return 0, "✓ Policy version 3 submitted (hash: 3f3f3f3f)\n", ""
		}
		return 1, "", "unexpected"
	}})
	rr, err := c.Rollback("s1", DeploymentReceipt{BackendRevision: "2"})
	if err != nil {
		t.Fatal(err)
	}
	if rr.RestoredRevision != "3" {
		t.Fatalf("got %s, must use gateway-reported revision", rr.RestoredRevision)
	}
	if setPath == "" {
		t.Fatal("set not called")
	}
	if _, err := os.Stat(setPath); !os.IsNotExist(err) {
		t.Fatal("tempfile leaked")
	}
}

func TestRollbackUnparseableReceiptFailsClosed(t *testing.T) {
	full := testdata(t, "policy_get_full.txt")
	c := New(Options{EnvScript: "/nonexistent/env.sh", PollInterval: -1, Runner: func(args []string) (int, string, string) {
		if len(args) >= 2 && args[0] == "policy" && args[1] == "get" {
			return 0, full, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			return 0, "unexpected output without version receipt\n", ""
		}
		return 1, "", "unexpected"
	}})
	if _, err := c.Rollback("s1", DeploymentReceipt{BackendRevision: "2"}); err == nil || !strings.Contains(err.Error(), "回执") {
		t.Fatalf("%v", err)
	}
}

func TestRollbackMissingAndInvalidRevision(t *testing.T) {
	c := backend(t, nil)
	if _, err := c.Rollback("s1", DeploymentReceipt{BackendRevision: ""}); err == nil || !strings.Contains(err.Error(), "backend_revision") {
		t.Fatalf("%v", err)
	}
	if _, err := c.Rollback("s1", DeploymentReceipt{BackendRevision: "12abc"}); err == nil || !strings.Contains(err.Error(), "backend_revision") {
		t.Fatalf("%v", err)
	}
}

func TestSandboxListDockerFallbackBelowV104(t *testing.T) {
	c := New(Options{
		EnvScript: "/nonexistent/env.sh", PollInterval: -1,
		Runner: func(args []string) (int, string, string) {
			if eq(args, "gateway", "info") {
				return 0, gatewayInfo, ""
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
	if _, err := c.ListTargets(); err == nil || !strings.Contains(err.Error(), "sandbox list") {
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
