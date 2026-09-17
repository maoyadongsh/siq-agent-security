package openshell

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func TestCommandChild(t *testing.T) {
	for idx, arg := range os.Args {
		if arg == "--emit" && idx+2 < len(os.Args) {
			fmt.Fprint(os.Stdout, os.Args[idx+1])
			fmt.Fprint(os.Stderr, os.Args[idx+2])
			os.Exit(0)
		}
	}
	if len(os.Args) < 3 || os.Args[len(os.Args)-2] != "--" {
		return
	}
	switch os.Args[len(os.Args)-1] {
	case "exact":
		fmt.Fprint(os.Stdout, strings.Repeat("a", 512))
		fmt.Fprint(os.Stderr, strings.Repeat("b", 512))
	case "overflow":
		fmt.Fprint(os.Stdout, strings.Repeat("a", 512))
		fmt.Fprint(os.Stderr, strings.Repeat("b", 513))
	case "endless":
		for {
			fmt.Fprint(os.Stdout, strings.Repeat("x", 8192))
		}
	case "sleep":
		time.Sleep(600 * time.Millisecond)
	case "inherited":
		child := exec.Command(os.Args[0], "-test.run=^TestCommandChild$", "--", "sleep")
		child.Stdout, child.Stderr = os.Stdout, os.Stderr
		if child.Start() != nil {
			os.Exit(2)
		}
	case "failed":
		fmt.Fprint(os.Stderr, "CANARY_DO_NOT_DISCLOSE")
		os.Exit(2)
	case "env":
		for _, key := range []string{"SIQ_AS_SECRET", "OPENSHELL_SECRET", "BASH_ENV", "LD_PRELOAD"} {
			if os.Getenv(key) != "" {
				fmt.Fprint(os.Stdout, "leaked")
			}
		}
		fmt.Fprint(os.Stdout, "clean")
	}
	os.Exit(0)
}

func TestSharedOutputBudgetVectors(t *testing.T) {
	var cases []struct {
		Name, Stdout, Stderr string
		Limit                int
		Allowed              bool
	}
	raw, err := os.ReadFile("../../../../testdata/openshell-command-budget.v1.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	bin, _ := os.Executable()
	for _, tc := range cases {
		t.Run(tc.Name, func(t *testing.T) {
			rc, out, diagnostic := runBoundedCommand([]string{bin, "-test.run=^TestCommandChild$", "--", "--emit", tc.Stdout, tc.Stderr}, (&Client{}).cleanEnv(), 3*time.Second, tc.Limit)
			if tc.Allowed {
				if rc != 0 || out != tc.Stdout || diagnostic != tc.Stderr {
					t.Fatal("incorrect successful byte capture")
				}
			} else if rc == 0 || out != "" || diagnostic != errOutputLimit {
				t.Fatal("overflow did not fail closed")
			}
		})
	}
}

func TestBoundedCommand(t *testing.T) {
	bin, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		mode, code string
		timeout    time.Duration
	}{
		{"exact", "", 3 * time.Second}, {"overflow", errOutputLimit, 3 * time.Second},
		{"endless", errOutputLimit, 3 * time.Second}, {"sleep", errCommandTimeout, 50 * time.Millisecond},
		{"inherited", errPipeTimeout, 3 * time.Second}, {"failed", errCommandFailed, 3 * time.Second},
	} {
		t.Run(tc.mode, func(t *testing.T) {
			started := time.Now()
			rc, out, diagnostic := runBoundedCommand([]string{bin, "-test.run=^TestCommandChild$", "--", tc.mode}, (&Client{}).cleanEnv(), tc.timeout, 1024)
			if tc.code == "" {
				if rc != 0 || len(out) != 512 || len(diagnostic) != 512 {
					t.Fatalf("unexpected result: %d %d %d", rc, len(out), len(diagnostic))
				}
			} else if rc == 0 || out != "" || diagnostic != tc.code {
				t.Fatalf("unexpected result: %d %q %q", rc, out, diagnostic)
			}
			if time.Since(started) > 2*time.Second {
				t.Fatal("unbounded command wait")
			}
		})
	}
}

func TestCommandEnvironmentAndErrorPrivacy(t *testing.T) {
	for _, key := range []string{"SIQ_AS_SECRET", "OPENSHELL_SECRET", "BASH_ENV"} {
		t.Setenv(key, "CANARY_DO_NOT_DISCLOSE")
	}
	bin, _ := os.Executable()
	rc, out, _ := runBoundedCommand([]string{bin, "-test.run=^TestCommandChild$", "--", "env"}, (&Client{}).cleanEnv(), 3*time.Second, 1024)
	if rc != 0 || out != "clean" {
		t.Fatal("environment leaked")
	}
	c := New(Options{Runner: func([]string) (int, string, string) { return 1, "", "CANARY_DO_NOT_DISCLOSE" }})
	_, err := c.cli("policy", "get", "PRIVATE_TARGET")
	if err == nil || err.Error() != errCommandFailed {
		t.Fatal("raw error or arguments escaped")
	}
	if _, _, err := parseSetReceipt("CANARY_DO_NOT_DISCLOSE"); err == nil || strings.Contains(err.Error(), "CANARY") {
		t.Fatal("malformed successful receipt leaked")
	}
}
