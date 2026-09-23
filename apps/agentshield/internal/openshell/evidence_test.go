package openshell

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestStatusShapeSharedVectors(t *testing.T) {
	raw, err := os.ReadFile("../../../../testdata/openshell-status-shape.v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct {
		Name, Text string
		Valid      bool
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			if looksLikeOpenShellStatus(tc.Text) != tc.Valid {
				t.Fatal("protocol shape mismatch")
			}
		})
	}
}

func TestProbeClearsStaleEvidenceAndRejectsDrift(t *testing.T) {
	endpoint, tls, broken, drift := "http://127.0.0.1:8080", "1", false, false
	c := New(Options{LookupEnv: func(k string) (string, bool) {
		v := map[string]string{envCLIBin: "/fixture/openshell", envEndpoint: endpoint, envInsecure: tls}[k]
		return v, v != ""
	}, Runner: func(args []string) (int, string, string) {
		switch strings.Join(args, " ") {
		case "gateway info":
			return 0, "Gateway Info\nGateway version: 0.0.104", ""
		case "status":
			if broken {
				return 1, "", "failure"
			}
			if drift {
				endpoint = "http://127.0.0.1:8081"
			}
			return 0, "Server Status\nGateway: fixture", ""
		}
		return 1, "", "unexpected"
	}})
	caps, err := c.Probe()
	if err != nil {
		t.Fatal(err)
	}
	if !caps.ConfigurationCapabilities["network.dynamic_update"] || caps.Capabilities["network_l34"].EvidenceLevel != "documented" {
		t.Fatal("missing provenance")
	}
	key := c.InvocationFingerprint()
	tls = "0"
	if c.InvocationFingerprint() == key {
		t.Fatal("TLS mode must invalidate evidence")
	}
	tls = "1"
	broken = true
	if _, err = c.Probe(); err == nil {
		t.Fatal("failed refresh accepted")
	}
	if c.cachedVersion(key) != "" || c.cachedGateway(key) != "" {
		t.Fatal("stale evidence survived failure")
	}
	broken = false
	drift = true
	if _, err = c.Probe(); err == nil || err.Error() != "openshell_configuration_changed" {
		t.Fatal("mid-probe drift accepted")
	}
}

func TestTargetDiagnosisIsReadOnlyAndBoundToExplicitEndpoint(t *testing.T) {
	explicit, broken, reads, writes := true, false, 0, 0
	base := loadPolicySafetyVectors(t).ReadCases[0].Output
	c := New(Options{EnvScript: "/fixture/env.sh", LookupEnv: func(k string) (string, bool) {
		if !explicit {
			return "", false
		}
		v := map[string]string{envCLIBin: "/fixture/openshell", envEndpoint: "http://127.0.0.1:8080", envInsecure: "1"}[k]
		return v, v != ""
	}, Runner: func(args []string) (int, string, string) {
		switch strings.Join(args, " ") {
		case "gateway info":
			return 0, "Gateway Info\nGateway version: 0.0.104", ""
		case "status":
			return 0, "Server Status\nGateway: fixture", ""
		case "policy get shared --full":
			reads++
			if broken {
				return 1, "", "failure"
			}
			return 0, base, ""
		}
		writes++
		return 1, "", "unexpected"
	}})
	d := c.DiagnoseTarget("shared")
	if d.State != StatePolicyReadable || d.Target != "shared" || d.Revision == "" || d.PolicyDigest == "" || d.ExpiresAt == "" {
		t.Fatalf("missing target evidence: %+v", d)
	}
	broken = true
	if d = c.DiagnoseTarget("shared"); d.State != StateEvidenceExpired || d.PolicyDigest != "" {
		t.Fatal("failed readback retained evidence")
	}
	explicit = false
	before := reads
	if d = c.DiagnoseTarget("shared"); d.State != StateIdentityUnconfirmed || reads != before {
		t.Fatal("indirect target upgraded")
	}
	if writes != 0 {
		t.Fatal("doctor attempted mutation")
	}
}

func TestLiveStatusVersionSharedVectors(t *testing.T) {
	raw, err := os.ReadFile("../../../../testdata/openshell-status-version.v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var cases []struct{ Name, Text, Version string }
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			if got := parseGatewayVersion(tc.Text); got != tc.Version {
				t.Fatalf("version %q, want %q", got, tc.Version)
			}
		})
	}
}

func TestProjectContextAlwaysBindsExplicitGatewayFingerprint(t *testing.T) {
	for _, key := range []string{"HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"} {
		t.Run(key, func(t *testing.T) {
			values := map[string]string{envCLIBin: "/fixture/openshell", envEndpoint: "https://127.0.0.1:17671", key: "/fixture/project-a"}
			c := New(Options{LookupEnv: func(k string) (string, bool) { v, ok := values[k]; return v, ok }})
			before := c.InvocationFingerprint()
			values[key] = "/fixture/project-b"
			if before == c.InvocationFingerprint() {
				t.Fatal("TLS/config context change reused old fingerprint")
			}
			stable := c.InvocationFingerprint()
			values["OPENAI_API_KEY"] = "fixture-only-never-forward"
			if stable != c.InvocationFingerprint() {
				t.Fatal("unrelated provider secret entered scope")
			}
		})
	}
}
