package openshell

import (
	"os"
	"strings"
	"testing"
)

func TestLooksLikeOpenShellGateway(t *testing.T) {
	if !looksLikeOpenShellGateway(gatewayInfo) {
		t.Fatal("fixture gateway info must be recognized")
	}
	if !looksLikeOpenShellGateway("Gateway Info\n  Gateway version: 0.0.104\n") {
		t.Fatal("version-only gateway info must be recognized")
	}
	if looksLikeOpenShellGateway("") {
		t.Fatal("empty must not be OpenShell")
	}
	if looksLikeOpenShellGateway("{\"ok\":true}") {
		t.Fatal("json must not be OpenShell")
	}
}

func TestLooksLikeForeignGateway(t *testing.T) {
	msg := "received corrupt message of type InvalidContentType"
	if !looksLikeForeignGateway(msg) {
		t.Fatal("InvalidContentType must be foreign")
	}
	if looksLikeForeignGateway(gatewayInfo) {
		t.Fatal("OpenShell pretty-print must not be foreign")
	}
}

func TestDiagnoseUnconfigured(t *testing.T) {
	c := New(Options{LookPath: missingPATH(), LookupEnv: func(string) (string, bool) { return "", false }})
	d := c.Diagnose()
	if d.CLIFound || d.ProbeOK || d.IdentityOK || d.Tier != "L0" || d.StartedGateway {
		t.Fatalf("%+v", d)
	}
	if d.Source != SourceNone || !strings.Contains(d.HumanNext, "不会代为启动") {
		t.Fatalf("%+v", d)
	}
}

func TestDiagnosePATHProbeOK(t *testing.T) {
	c := New(Options{
		LookPath:     func(string) (string, error) { return "/usr/bin/openshell", nil },
		PollInterval: -1,
		Runner: fake(map[string]struct {
			rc     int
			stdout string
			stderr string
		}{
			k("gateway", "info"): {0, gatewayInfo, ""},
			k("status"):          {0, "Server Status\n  Gateway: siq-openshell-dev\n", ""},
		}),
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	d := c.Diagnose()
	if !d.CLIFound || d.Source != SourcePath || d.CLIPath != "/usr/bin/openshell" {
		t.Fatalf("%+v", d)
	}
	if !d.ProbeOK || !d.IdentityOK || d.Tier != "L3" || d.StartedGateway {
		t.Fatalf("%+v", d)
	}
	if d.ActiveGateway != "siq-openshell-dev" {
		t.Fatalf("probed gateway %q", d.ActiveGateway)
	}
	if d.HumanNext != MsgReady {
		t.Fatalf("human_next %q", d.HumanNext)
	}
}

func TestDiagnoseWrongProcess(t *testing.T) {
	c := New(Options{
		LookPath:     func(string) (string, error) { return "/usr/bin/openshell", nil },
		PollInterval: -1,
		Runner: fake(map[string]struct {
			rc     int
			stdout string
			stderr string
		}{
			k("gateway", "info"): {1, "", "received corrupt message of type InvalidContentType"},
		}),
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	d := c.Diagnose()
	if d.ProbeOK || d.IdentityOK || d.Tier != "L0" || d.StartedGateway {
		t.Fatalf("%+v", d)
	}
	if d.HumanNext != MsgWrongProcess {
		t.Fatalf("human_next %q", d.HumanNext)
	}
}

func TestDiagnoseWrongProcessWhenInfoIsLocalConfig(t *testing.T) {
	c := New(Options{
		LookPath:     func(string) (string, error) { return "/usr/bin/openshell", nil },
		PollInterval: -1,
		Runner: fake(map[string]struct {
			rc     int
			stdout string
			stderr string
		}{
			k("gateway", "info"): {0, gatewayInfo, ""},
			k("status"):          {1, "", "received corrupt message of type InvalidContentType"},
		}),
		LookupEnv: func(string) (string, bool) { return "", false },
	})
	d := c.Diagnose()
	if d.ProbeOK || d.IdentityOK || d.Tier != "L0" || d.HumanNext != MsgWrongProcess {
		t.Fatalf("local gateway info must not imply L3: %+v", d)
	}
}

func TestDiagnoseNeverStartsGateway(t *testing.T) {
	d := UnconfiguredDiagnosis()
	if d.StartedGateway {
		t.Fatal("started_gateway must be false")
	}
}

func TestReadActiveGatewayNameSafe(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("XDG_CONFIG_HOME", dir)
	t.Setenv("HOME", dir)
	if got := readActiveGatewayName(); got != "" {
		t.Fatalf("missing file: %q", got)
	}
	os.MkdirAll(dir+"/openshell", 0o700)
	if err := os.WriteFile(dir+"/openshell/active_gateway", []byte("nemoclaw\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := readActiveGatewayName(); got != "nemoclaw" {
		t.Fatalf("got %q", got)
	}
	if err := os.WriteFile(dir+"/openshell/active_gateway", []byte("../../etc/passwd\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := readActiveGatewayName(); got != "" {
		t.Fatalf("path-like name must be dropped: %q", got)
	}
}
