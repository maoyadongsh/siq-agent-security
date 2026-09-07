package receipt

import (
	"bufio"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// Kill a separate process after durable publication, leaving no deferred cleanup
// or graceful Engine shutdown to supply recovery state.
func TestActionRecoveryAfterProcessKill(t *testing.T) {
	const marker = "SIQ_TEST_ACTION_CRASH_MODE"
	if mode := os.Getenv(marker); mode != "" {
		pack, err := rulepack.Builtin()
		if err != nil {
			t.Fatal(err)
		}
		chain, err := OpenChain(os.Getenv("SIQ_TEST_ACTION_CRASH_DIR"), "local", key(t))
		if err != nil {
			t.Fatal(err)
		}
		g := deployedGrant(t, "hermes", false)
		engine, err := New(Options{Pack: pack, Chain: chain, Grants: func(string, string) *grant.Grant { return g }, EnforcementMode: "block"})
		if err != nil {
			t.Fatal(err)
		}
		request := req("hermes", "read_file", map[string]any{"path": "/work/report"})
		d, err := engine.Decide(request)
		if err != nil || d.Action != ActionAllow {
			t.Fatal(d, err)
		}
		if mode == "observed" {
			if _, err = engine.Observe(correlatedRequest(request, d), "result"); err != nil {
				t.Fatal(err)
			}
		}
		if err = json.NewEncoder(os.Stdout).Encode(d); err != nil {
			t.Fatal(err)
		}
		_, _ = io.Copy(io.Discard, os.Stdin)
		return
	}
	for _, mode := range []string{"pending", "observed"} {
		t.Run(mode, func(t *testing.T) {
			dir := t.TempDir()
			cmd := exec.Command(os.Args[0], "-test.run=^TestActionRecoveryAfterProcessKill$")
			cmd.Env = append(os.Environ(), marker+"="+mode, "SIQ_TEST_ACTION_CRASH_DIR="+dir)
			stdout, err := cmd.StdoutPipe()
			if err != nil {
				t.Fatal(err)
			}
			stdin, err := cmd.StdinPipe()
			if err != nil {
				t.Fatal(err)
			}
			defer stdin.Close()
			cmd.Stderr = os.Stderr
			if err = cmd.Start(); err != nil {
				t.Fatal(err)
			}
			defer func() { _ = cmd.Process.Kill(); _ = cmd.Wait() }()
			ready := make(chan []byte, 1)
			go func() { line, _ := bufio.NewReader(stdout).ReadBytes('\n'); ready <- line }()
			var d Decision
			select {
			case line := <-ready:
				if err = json.Unmarshal(line, &d); err != nil {
					t.Fatal(err)
				}
			case <-time.After(20 * time.Second):
				t.Fatal("child did not publish decision")
			}
			if err = cmd.Process.Kill(); err != nil {
				t.Fatal(err)
			}
			_ = cmd.Wait()
			pack, err := rulepack.Builtin()
			if err != nil {
				t.Fatal(err)
			}
			chain, err := OpenChain(dir, "local", key(t))
			if err != nil {
				t.Fatal(err)
			}
			opts := Options{Pack: pack, Chain: chain, EnforcementMode: "block"}
			engine, err := New(opts)
			if err != nil {
				t.Fatal(err)
			}
			request := correlatedRequest(req("hermes", "read_file", map[string]any{"path": "/work/report"}), &d)
			observed, err := engine.Observe(request, "result")
			if err != nil || observed.DecisionReceiptID != d.Receipt.ReceiptID {
				t.Fatal(observed, err)
			}
			again, err := engine.Observe(request, "result")
			if err != nil || again.ReceiptID != observed.ReceiptID {
				t.Fatal(again, err)
			}
			all, err := chain.Read()
			if err != nil || len(all) != 2 {
				t.Fatal(len(all), err)
			}
			if err = Verify(all, key(t).Public()); err != nil {
				t.Fatal(err)
			}
		})
	}
}
