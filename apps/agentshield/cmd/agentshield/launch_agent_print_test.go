package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func syntheticLaunchPrint(uid int, label, source, program, stateDir string, pid int64, lastExit, argv1 string) string {
	if argv1 == "" {
		argv1 = "serve"
	}
	if lastExit == "" {
		lastExit = "(never exited)"
	}
	state := "not running"
	pidLine := ""
	if pid > 0 {
		state = "running"
		pidLine = "\tpid = " + strconv.FormatInt(pid, 10) + "\n"
	}
	return fmt.Sprintf("gui/%d/%s = {\n\tactive count = 0\n\tpath = %s\n\ttype = LaunchAgent\n\tstate = %s\n\tprogram = %s\n\targuments = {\n\t\t%s\n\t\t%s\n\t}\n\tstdout path = /dev/null\n\tstderr path = /dev/null\n\tinherited environment = {\n\t}\n\tdefault environment = {\n\t}\n\tenvironment = {\n\t\tOSLogRateLimit => 64\n\t\tSIQ_AGENT_SECURITY_STATE_DIR => %s\n\t\tXPC_SERVICE_NAME => %s\n\t}\n\tdomain = gui/%d [100025]\n\tumask = 77\n\tasid = 1\n\tminimum runtime = 10\n\texit timeout = 30\n\truns = 0\n%s\tlast exit code = %s\n\tspawn type = daemon (3)\n\tjetsam priority = 40\n\tjetsam memory limit (active) = (unlimited)\n\tjetsam memory limit (inactive) = (unlimited)\n\tjetsamproperties category = daemon\n\tjetsam thread limit = 32\n\tcpumon = default\n\tproperties = inferred program\n}\n", uid, label, source, state, program, program, argv1, stateDir, label, uid, pidLine, lastExit)
}

func mustResolve(t *testing.T, path string) string {
	t.Helper()
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatal(err)
	}
	return resolved
}

func mustLaunchPrint(t *testing.T, rendered, source string, pid int64, lastExit, argv1 string) string {
	t.Helper()
	wanted, err := decodeLaunchPlist(rendered)
	if err != nil {
		t.Fatal(err)
	}
	label, _ := wanted["Label"].(string)
	argv, ok := stringSlice(wanted["ProgramArguments"])
	if !ok || len(argv) != 2 {
		t.Fatal("invalid fixture arguments")
	}
	env, _ := wanted["EnvironmentVariables"].(map[string]any)
	stateDir, _ := env["SIQ_AGENT_SECURITY_STATE_DIR"].(string)
	return syntheticLaunchPrint(501, label, mustResolve(t, source), argv[0], stateDir, pid, lastExit, argv1)
}

func TestDecodeLaunchPrintAcceptsDarwinShape(t *testing.T) {
	sourceDir := t.TempDir()
	source := filepath.Join(sourceDir, "job.plist")
	if err := os.WriteFile(source, []byte("plist"), 0600); err != nil {
		t.Fatal(err)
	}
	label := "dev.siq.agent-security." + strings.Repeat("a", 64)
	raw := syntheticLaunchPrint(501, label, mustResolve(t, source), "/bin/siq", "/state", 123, "(never exited)", "")
	tree, err := decodeLaunchPrint(raw, 501, label)
	if err != nil {
		t.Fatal(err)
	}
	if tree["type"] != "LaunchAgent" || tree["state"] != "running" || tree["pid"] != "123" {
		t.Fatal(tree)
	}
}

func TestDecodeLaunchPrintRejectsListDashXAndOpenStep(t *testing.T) {
	label := "dev.siq.agent-security." + strings.Repeat("a", 64)
	for _, raw := range []string{
		"<?xml version=\"1.0\"?>\n<plist version=\"1.0\"><dict></dict></plist>\n",
		"{\n\t\"Label\" = \"x\";\n};\n",
		"Could not find service \"-x\" in domain for port\n",
		"gui/501/" + label + " = {\n\tpath = /x\n",
	} {
		if _, err := decodeLaunchPrint(raw, 501, label); err == nil {
			t.Fatal("accepted", raw)
		}
	}
}

func TestVerifyLaunchPrintRejectsDrift(t *testing.T) {
	expected, err := os.ReadFile("../../testdata/contracts/launch-agent.sample.plist")
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(t.TempDir(), "source.plist")
	if err := os.WriteFile(source, expected, 0600); err != nil {
		t.Fatal(err)
	}
	wanted, err := decodeLaunchPlist(string(expected))
	if err != nil {
		t.Fatal(err)
	}
	good := mustLaunchPrint(t, string(expected), source, 0, "", "")
	tree, err := decodeLaunchPrint(good, 501, wanted["Label"].(string))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifyLaunchPrint(wanted, tree, 501, mustResolve(t, source)); err != nil {
		t.Fatal(err)
	}
	wrong := strings.Replace(good, "serve", "other", 1)
	tree, err = decodeLaunchPrint(wrong, 501, wanted["Label"].(string))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifyLaunchPrint(wanted, tree, 501, mustResolve(t, source)); err == nil {
		t.Fatal("argv drift accepted")
	}
}
