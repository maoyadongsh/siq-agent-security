package adapterinstall

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/state"
)

func putTestFile(t *testing.T, path string, data []byte, mode os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, mode); err != nil {
		t.Fatal(err)
	}
}
func testPlan(t *testing.T, o Options, action string) *Plan {
	t.Helper()
	p, err := Prepare(o, action)
	if err != nil {
		t.Fatal(err)
	}
	return p
}
func assertBefore(t *testing.T, p *Plan) {
	t.Helper()
	for _, op := range p.payload.Files {
		got, err := readImage(p.payload.Options.Home, op.Path)
		if err != nil || !sameImage(got, op.Before) {
			t.Fatalf("before not restored: %s", op.Path)
		}
	}
}

func TestPlanReadOnlyAndPinsNoOpInputs(t *testing.T) {
	o := testOpts(t, Hermes)
	p := testPlan(t, o, "install")
	if exists(filepath.Join(o.Home, ".hermes")) {
		t.Fatal("preview wrote platform")
	}
	entries, _ := os.ReadDir(o.StateDir)
	if len(entries) != 0 {
		t.Fatal("preview wrote state")
	}
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	p = testPlan(t, o, "install")
	if len(p.payload.Files) != 0 {
		t.Fatal("reinstall should have no file changes")
	}
	path := filepath.Join(o.Home, ".hermes", "plugins", "siq-agent-security", "config.json")
	putTestFile(t, path, []byte("external change"), 0600)
	if _, err := Apply(p); !errors.Is(err, ErrPlanChanged) {
		t.Fatalf("unchanged input was not pinned: %v", err)
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "external change" {
		t.Fatal("external change overwritten")
	}
}

func TestPlanPreflightRejectsWholeOperation(t *testing.T) {
	for _, kind := range []string{"last-file", "binary", "expired", "digest", "revision"} {
		t.Run(kind, func(t *testing.T) {
			o := testOpts(t, OpenClaw)
			p := testPlan(t, o, "install")
			switch kind {
			case "last-file":
				op := p.payload.Files[len(p.payload.Files)-1]
				putTestFile(t, op.Path, []byte("external"), 0600)
			case "binary":
				putTestFile(t, o.Binary, []byte("changed program"), 0700)
			case "expired":
				p.payload.View.ExpiresAt = time.Now().Add(-time.Minute).UTC().Format(time.RFC3339)
			case "digest":
				p.payload.View.PlanDigest = strings.Repeat("f", 64)
			case "revision":
				other := testPlan(t, o, "install")
				if _, err := Apply(other); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := Apply(p); err == nil {
				t.Fatal("invalid preview accepted")
			}
			if kind != "revision" && exists(p.payload.Files[0].Path) {
				t.Fatal("preflight wrote initial file")
			}
		})
	}
}

func TestTransactionBoundaryFailureRestoresFiles(t *testing.T) {
	for _, boundary := range []string{"prepared", "file:0", "file:2", "audited"} {
		t.Run(boundary, func(t *testing.T) {
			o := testOpts(t, Hermes)
			path := filepath.Join(o.Home, ".local", "bin", "hermes-skills-install")
			putTestFile(t, path, []byte("original user wrapper"), 0750)
			p := testPlan(t, o, "install")
			transactionBoundary = func(at string) error {
				if at == boundary {
					return errors.New("injected interruption")
				}
				return nil
			}
			t.Cleanup(func() { transactionBoundary = func(string) error { return nil } })
			res, err := Apply(p)
			if err == nil || res.Action != "rolled_back" {
				t.Fatalf("failed operation reported success: %v %v", res, err)
			}
			assertBefore(t, p)
			if _, err := Prepare(o, "install"); err != nil {
				t.Fatalf("rolled back claim blocked new preview: %v", err)
			}
		})
	}
}

func TestTransactionConflictPreservesForeignEditAndCanRecover(t *testing.T) {
	o := testOpts(t, Hermes)
	p := testPlan(t, o, "install")
	first := p.payload.Files[0]
	transactionBoundary = func(at string) error {
		if at == "file:1" {
			putTestFile(t, first.Path, []byte("external after apply"), 0600)
			return errors.New("stop")
		}
		return nil
	}
	t.Cleanup(func() { transactionBoundary = func(string) error { return nil } })
	res, err := Apply(p)
	if !errors.Is(err, ErrRecoveryRequired) || res.Action != "recovery_required" {
		t.Fatalf("conflict lost: %v %v", res, err)
	}
	raw, _ := os.ReadFile(first.Path)
	if string(raw) != "external after apply" {
		t.Fatal("external edit overwritten")
	}
	if _, err := Prepare(o, "install"); !errors.Is(err, ErrRecoveryRequired) {
		t.Fatal("unfinished operation bypassed")
	}
	if _, err := Recover(o.StateDir, o.Platform); !errors.Is(err, ErrRecoveryRequired) {
		t.Fatal("recovery overwrote external edit")
	}
	// An explicit local repair restores the known before image; recovery can finish.
	if err := os.Remove(first.Path); err != nil {
		t.Fatal(err)
	}
	res, err = Recover(o.StateDir, o.Platform)
	if err != nil || res.Action != "rolled_back" {
		t.Fatalf("recovery: %v %v", res, err)
	}
	assertBefore(t, p)
}

func TestTransactionAuditFailureAndEncryptedRecovery(t *testing.T) {
	for _, when := range []string{"start", "completion"} {
		t.Run(when, func(t *testing.T) {
			o := testOpts(t, CodeBuddy)
			path := filepath.Join(o.Home, ".codebuddy", "settings.json")
			secret := "private-fixture-do-not-leak"
			putTestFile(t, path, []byte(`{"private":"`+secret+`"}`), 0600)
			p := testPlan(t, o, "install")
			audit := filepath.Join(o.StateDir, "audit.jsonl")
			if when == "start" {
				if err := os.Mkdir(audit, 0700); err != nil {
					t.Fatal(err)
				}
			} else {
				transactionBoundary = func(at string) error {
					if at == fmt.Sprintf("file:%d", len(p.payload.Files)-1) {
						if err := os.Remove(audit); err != nil {
							t.Fatal(err)
						}
						if err := os.Mkdir(audit, 0700); err != nil {
							t.Fatal(err)
						}
					}
					return nil
				}
				t.Cleanup(func() { transactionBoundary = func(string) error { return nil } })
			}
			if _, err := Apply(p); err == nil {
				t.Fatal("audit failure reported success")
			}
			assertBefore(t, p)
			sealed, err := os.ReadFile(transactionPath(o.StateDir, p.View().PlanID, ".sealed"))
			if err != nil || bytes.Contains(sealed, []byte(secret)) {
				t.Fatal("recovery material leaked or missing")
			}
			view, _ := json.Marshal(p.View())
			if bytes.Contains(view, []byte(secret)) {
				t.Fatal("preview leaked plaintext")
			}
		})
	}
}

func TestRecoveryCannotTakeActiveWriter(t *testing.T) {
	o := testOpts(t, Hermes)
	guard, err := state.AcquireWriter(filepath.Join(o.StateDir, "adapter-write"))
	if err != nil {
		t.Fatal(err)
	}
	defer guard.Release()
	if _, err := Apply(testPlan(t, o, "install")); !errors.Is(err, state.ErrWriterBusy) {
		t.Fatal("apply ignored live writer")
	}
	if _, err := Recover(o.StateDir, Hermes); !errors.Is(err, state.ErrWriterBusy) {
		t.Fatal("recovery ignored live writer")
	}
}

func TestAdapterCrashHelper(t *testing.T) {
	raw := os.Getenv("SIQ_TEST_ADAPTER_CRASH_OPTIONS")
	if raw == "" {
		return
	}
	var o Options
	if json.Unmarshal([]byte(raw), &o) != nil {
		os.Exit(91)
	}
	transactionBoundary = func(at string) error {
		if at == os.Getenv("SIQ_TEST_ADAPTER_CRASH_BOUNDARY") {
			os.Exit(73)
		}
		return nil
	}
	p, err := Prepare(o, "install")
	if err != nil {
		os.Exit(92)
	}
	_, _ = Apply(p)
	os.Exit(93)
}

func TestAdapterRealProcessDeathRecovery(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("writer implementation conservatively cannot prove Windows process death; requires native lifecycle work")
	}
	for _, boundary := range []string{"prepared", "file:1", "audited"} {
		t.Run(boundary, func(t *testing.T) {
			o := testOpts(t, Hermes)
			expected := testPlan(t, o, "install")
			raw, _ := json.Marshal(o)
			cmd := exec.Command(os.Args[0], "-test.run=^TestAdapterCrashHelper$")
			cmd.Env = append(os.Environ(), "SIQ_TEST_ADAPTER_CRASH_OPTIONS="+string(raw), "SIQ_TEST_ADAPTER_CRASH_BOUNDARY="+boundary)
			err := cmd.Run()
			var exited *exec.ExitError
			if !errors.As(err, &exited) || exited.ExitCode() != 73 {
				t.Fatalf("helper did not reach crash boundary: %v", err)
			}
			if _, err := Prepare(o, "install"); !errors.Is(err, ErrRecoveryRequired) {
				t.Fatal("crashed operation not detected")
			}
			res, err := Recover(o.StateDir, Hermes)
			if err != nil || res.Action != "rolled_back" {
				t.Fatalf("dead writer recovery: %v %v", res, err)
			}
			assertBefore(t, expected)
		})
	}
}

func TestTransactionPrivateStoreRejectsSymlinks(t *testing.T) {
	for _, name := range []string{"adapter-transactions", "adapter-operations", "adapter-write"} {
		t.Run(name, func(t *testing.T) {
			o := testOpts(t, Hermes)
			target := t.TempDir()
			if err := os.Symlink(target, filepath.Join(o.StateDir, name)); err != nil {
				t.Skip(err)
			}
			if _, err := Prepare(o, "install"); err == nil {
				t.Fatal("symlink store accepted")
			}
			entries, _ := os.ReadDir(target)
			if len(entries) != 0 {
				t.Fatal("outside files written")
			}
		})
	}
}

func TestUninstallKeepsUnknownFilesAndWrapperMode(t *testing.T) {
	o := testOpts(t, Hermes)
	wrapper := filepath.Join(o.Home, ".local", "bin", "hermes-skills-install")
	putTestFile(t, wrapper, []byte("user wrapper"), 0750)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	unknown := filepath.Join(o.Home, ".hermes", "plugins", "siq-agent-security", "my-notes.txt")
	putTestFile(t, unknown, []byte("keep"), 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(unknown)
	if err != nil || string(raw) != "keep" {
		t.Fatal("unknown file deleted")
	}
	image, err := readImage(o.Home, wrapper)
	if err != nil || string(image.Data) != "user wrapper" || runtime.GOOS != "windows" && image.Mode != 0750 {
		t.Fatal("wrapper not restored")
	}
}

func TestHermesWrapperQuotesPathsAndRefusesFailedAdmission(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX wrapper is not installed on Windows")
	}
	for _, status := range []string{"0", "3"} {
		t.Run(status, func(t *testing.T) {
			o := testOpts(t, Hermes)
			o.Binary = filepath.Join(o.Home, "siq ' $(touch injected) `touch injected2`")
			o.StateDir = filepath.Join(o.Home, "state ' $(touch injected3)")
			script := []byte("#!/bin/sh\nprintf '%s' \"$SIQ_AGENT_SECURITY_STATE_DIR\" > \"$SIQ_TEST_STATE_OUTPUT\"\nexit \"$SIQ_TEST_ADMIT_EXIT\"\n")
			putTestFile(t, o.Binary, script, 0700)
			fakeBin := filepath.Join(o.Home, "tools")
			putTestFile(t, filepath.Join(fakeBin, "hermes"), []byte("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SIQ_TEST_HERMES_OUTPUT\"\n"), 0700)
			wrapper := filepath.Join(o.Home, "wrapper")
			putTestFile(t, wrapper, hermesWrapper(o), 0700)
			stateOut, hostOut := filepath.Join(o.Home, "state-output"), filepath.Join(o.Home, "hermes-output")
			cmd := exec.Command("sh", wrapper, "source with spaces", "--fixture")
			cmd.Dir = o.Home
			cmd.Env = append(os.Environ(), "PATH="+fakeBin+string(os.PathListSeparator)+os.Getenv("PATH"), "SIQ_TEST_ADMIT_EXIT="+status, "SIQ_TEST_STATE_OUTPUT="+stateOut, "SIQ_TEST_HERMES_OUTPUT="+hostOut)
			output, err := cmd.CombinedOutput()
			if status == "0" && err != nil {
				t.Fatalf("wrapper failed: %v %s", err, output)
			}
			if status != "0" && err == nil {
				t.Fatal("failed admission ignored")
			}
			raw, _ := os.ReadFile(stateOut)
			if string(raw) != o.StateDir {
				t.Fatal("state path expansion or quoting error")
			}
			for _, name := range []string{"injected", "injected2", "injected3"} {
				if exists(filepath.Join(o.Home, name)) {
					t.Fatal("path evaluated as shell code")
				}
			}
			if status == "0" {
				raw, _ := os.ReadFile(hostOut)
				if string(raw) != "skills\ninstall\nsource with spaces\n--fixture\n" {
					t.Fatal("platform arguments changed")
				}
			} else if exists(hostOut) {
				t.Fatal("platform installed after rejected admission")
			}
		})
	}
}

func TestUninstallRestoresPreexistingPluginRegistration(t *testing.T) {
	o := testOpts(t, OpenClaw)
	plugin := filepath.Join(o.Home, ".openclaw", "plugins", "siq-agent-security")
	path := filepath.Join(o.Home, ".openclaw", "openclaw.json")
	original := map[string]any{"plugins": map[string]any{"allow": []any{"siq-agent-security", "other"}, "load": map[string]any{"paths": []any{plugin}}, "entries": map[string]any{"siq-agent-security": map[string]any{"enabled": false, "config": map[string]any{"user": "original"}}}}}
	putTestFile(t, path, encodePlanJSON(original), 0600)
	if _, err := Install(o); err != nil {
		t.Fatal(err)
	}
	live, err := readJSONObject(path)
	if err != nil {
		t.Fatal(err)
	}
	plugins := live["plugins"].(map[string]any)
	entry := plugins["entries"].(map[string]any)["siq-agent-security"].(map[string]any)
	entry["added_later"] = "keep"
	putTestFile(t, path, encodePlanJSON(live), 0600)
	if _, err := Uninstall(o); err != nil {
		t.Fatal(err)
	}
	restored, _ := readJSONObject(path)
	plugins = restored["plugins"].(map[string]any)
	entry = plugins["entries"].(map[string]any)["siq-agent-security"].(map[string]any)
	if entry["enabled"] != false || entry["added_later"] != "keep" || entry["config"] == nil {
		t.Fatal("preexisting entry or user additions lost")
	}
	if len(plugins["allow"].([]any)) != 2 || len(plugins["load"].(map[string]any)["paths"].([]any)) != 1 {
		t.Fatal("preexisting registration removed")
	}
}

func TestRecoveryRejectsTamperedCiphertext(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("requires proven process-death recovery")
	}
	o := testOpts(t, Hermes)
	raw, _ := json.Marshal(o)
	cmd := exec.Command(os.Args[0], "-test.run=^TestAdapterCrashHelper$")
	cmd.Env = append(os.Environ(), "SIQ_TEST_ADAPTER_CRASH_OPTIONS="+string(raw), "SIQ_TEST_ADAPTER_CRASH_BOUNDARY=file:1")
	err := cmd.Run()
	var exited *exec.ExitError
	if !errors.As(err, &exited) || exited.ExitCode() != 73 {
		t.Fatal("crash fixture failed")
	}
	_, claimRaw, err := (&state.Store{Dir: o.StateDir}).LatestSeq("adapter-operations", Hermes)
	if err != nil {
		t.Fatal(err)
	}
	var claim operationClaim
	if err := json.Unmarshal(claimRaw, &claim); err != nil {
		t.Fatal(err)
	}
	plan, err := unsealPlan(o.StateDir, claim)
	if err != nil {
		t.Fatal(err)
	}
	current := map[string]fileImage{}
	for _, op := range plan.payload.Files {
		image, err := readImage(o.Home, op.Path)
		if err != nil {
			t.Fatal(err)
		}
		current[op.Path] = image
	}
	path := transactionPath(o.StateDir, claim.ID, ".sealed")
	sealed, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	sealed[len(sealed)-1] ^= 1
	putTestFile(t, path, sealed, 0600)
	if _, err := Recover(o.StateDir, Hermes); err == nil {
		t.Fatal("tampered journal accepted")
	}
	for path, before := range current {
		after, err := readImage(o.Home, path)
		if err != nil || !sameImage(before, after) {
			t.Fatal("recovery wrote before authentication")
		}
	}
}

func TestCommittedOwnershipRequiresAuthenticatedJournal(t *testing.T) {
	o := testOpts(t, Hermes)
	p := testPlan(t, o, "install")
	if _, err := Apply(p); err != nil {
		t.Fatal(err)
	}
	path := transactionPath(o.StateDir, p.View().PlanID, ".sealed")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	raw[len(raw)-1] ^= 1
	putTestFile(t, path, raw, 0600)
	if _, err := Prepare(o, "uninstall"); err == nil {
		t.Fatal("committed plaintext ownership accepted without authentic journal")
	}
	if !exists(filepath.Join(o.configRoot(), "plugins", "siq-agent-security", "plugin.yaml")) {
		t.Fatal("invalid ownership removed host files")
	}
}

func TestApplyReadbackRejectsConcurrentEditBeforeCompletion(t *testing.T) {
	o := testOpts(t, Hermes)
	p := testPlan(t, o, "install")
	first := p.payload.Files[0]
	transactionBoundary = func(at string) error {
		if at == fmt.Sprintf("file:%d", len(p.payload.Files)-1) {
			putTestFile(t, first.Path, []byte("external before completion"), 0600)
		}
		return nil
	}
	t.Cleanup(func() { transactionBoundary = func(string) error { return nil } })
	if _, err := Apply(p); !errors.Is(err, ErrRecoveryRequired) {
		t.Fatal("readback drift reported successful")
	}
	raw, _ := os.ReadFile(first.Path)
	if string(raw) != "external before completion" {
		t.Fatal("concurrent edit overwritten")
	}
}
