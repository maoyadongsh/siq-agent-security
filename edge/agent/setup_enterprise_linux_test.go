//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

func TestEnterpriseSetupOrderedIdentityBranches(t *testing.T) {
	for _, kind := range []string{"new", "pending", "registered"} {
		for _, start := range []bool{false, true} {
			t.Run(kind, func(t *testing.T) {
				var calls []string
				var out bytes.Buffer
				step := func(name string) func() error { return func() error { calls = append(calls, name); return nil } }
				err := runEnterpriseSetup(context.Background(), kind, start, &out, setupActions{
					prepare:  func() (string, error) { calls = append(calls, "prepare"); return "/fixture/stage", nil },
					register: step("register"), recover: step("recover"), confirm: step("consent"),
					install: func(path string) error {
						if path != "/fixture/stage" {
							t.Fatal("staged path lost")
						}
						return step("service")()
					},
				})
				want := []string{"prepare"}
				if kind == "new" {
					want = append(want, "register")
				}
				if kind == "pending" {
					want = append(want, "recover")
				}
				want = append(want, "consent", "service")
				if err != nil || !reflect.DeepEqual(calls, want) {
					t.Fatal("wrong setup sequence")
				}
				status := "configured_only"
				if start {
					status = "service_active_only"
				}
				if !strings.Contains(out.String(), status) || !strings.Contains(out.String(), "stage_path") {
					t.Fatal("missing progress")
				}
				lines := strings.Split(strings.TrimSpace(out.String()), "\n")
				if len(lines) != 4 {
					t.Fatalf("enterprise-setup/v1 progress must end at service, got %d records: %s", len(lines), out.String())
				}
				var gotProgress []string
				for _, line := range lines {
					var record struct {
						Phase  string `json:"phase"`
						Status string `json:"status"`
					}
					if json.Unmarshal([]byte(line), &record) != nil {
						t.Fatalf("invalid progress record: %s", line)
					}
					gotProgress = append(gotProgress, record.Phase+"="+record.Status)
				}
				wantProgress := []string{"prepare=staged_only", "identity=registered_only", "consent=discovery_scope_saved", "service=" + status}
				if !reflect.DeepEqual(gotProgress, wantProgress) {
					t.Fatalf("enterprise-setup/v1 progress changed: %v", gotProgress)
				}
			})
		}
	}
}

func TestSetupScheduleConfirmationPrecedesServiceAndFailureStops(t *testing.T) {
	for _, fail := range []bool{false, true} {
		var calls []string
		var out bytes.Buffer
		step := func(name string) func() error {
			return func() error { calls = append(calls, name); return nil }
		}
		err := runEnterpriseSetup(context.Background(), "registered", true, &out, setupActions{
			prepare: func() (string, error) { calls = append(calls, "prepare"); return "/fixture/stage", nil },
			confirm: step("consent"),
			schedule: func() error {
				calls = append(calls, "schedule")
				if fail {
					return errors.New("synthetic confirmation failure")
				}
				return nil
			},
			install: func(string) error { return step("service")() },
		})
		want := []string{"prepare", "consent", "schedule"}
		if !fail {
			want = append(want, "service")
		}
		if !reflect.DeepEqual(calls, want) || (err != nil) != fail {
			t.Fatalf("wrong sequence calls=%v err=%v", calls, err)
		}
		if strings.Contains(out.String(), "confirmation_acknowledged_only") == fail ||
			strings.Contains(out.String(), "service_active_only") == fail {
			t.Fatal("incorrect progress claim")
		}
	}
}

func TestSetupScheduleRecoveryErrorsAreAllowlisted(t *testing.T) {
	for _, cause := range []error{errScheduleConfirmationUnknown, errScheduleReceiptUnstored, errors.New("private-upstream-body")} {
		err := runEnterpriseSetup(context.Background(), "registered", true, &bytes.Buffer{}, setupActions{
			prepare:  func() (string, error) { return "/fixture/stage", nil },
			confirm:  func() error { return nil },
			schedule: func() error { return cause },
			install:  func(string) error { t.Fatal("installed after schedule failure"); return nil },
		})
		if err == nil || !strings.Contains(err.Error(), "service installation not attempted") || strings.Contains(err.Error(), "private-upstream-body") {
			t.Fatal("unsafe recovery error", err)
		}
		if cause == errScheduleConfirmationUnknown || cause == errScheduleReceiptUnstored {
			if !errors.Is(err, cause) {
				t.Fatal("lost safe recovery category")
			}
		}
	}
}

func TestSetupScheduleFlagsCannotImplyConsent(t *testing.T) {
	id, digest := "eds-"+strings.Repeat("a", 32), strings.Repeat("b", 64)
	for _, args := range [][]string{
		{"--schedule-id", id}, {"--confirm-schedule-sha256", digest},
		{"--resume-schedule"},
		{"--schedule-id", id, "--resume-schedule", "--confirm-schedule-sha256", digest},
		{"--schedule-id", id, "--confirm-schedule-sha256", digest, "--interactive"},
		{"--schedule-id", id, "--confirm-schedule-sha256", digest, "--review-only"},
	} {
		var out bytes.Buffer
		if setupEnterprise(context.Background(), args, &out) == nil || out.Len() != 0 {
			t.Fatalf("invalid consent accepted: %v", args)
		}
	}
	var help bytes.Buffer
	if setupEnterprise(context.Background(), []string{"--help"}, &help) != nil || !strings.Contains(help.String(), "--confirm-schedule-sha256") {
		t.Fatal("missing schedule help")
	}
}

func TestSetupScheduleArgsSeparateInteractiveConsent(t *testing.T) {
	id, digest := "eds-"+strings.Repeat("a", 32), strings.Repeat("b", 64)
	for _, tc := range []struct {
		id, digest          string
		resume, interactive bool
		want                []string
	}{
		{id, "", false, true, []string{"--interactive", "--schedule-id", id}},
		{"", "", true, true, []string{"--interactive", "--resume"}},
		{id, digest, false, false, []string{"--confirm-intent-sha256", digest, "--schedule-id", id}},
		{"", digest, true, false, []string{"--confirm-intent-sha256", digest, "--resume"}},
		{id, digest, false, true, nil}, {id, "", false, false, nil},
		{"", "", false, true, nil}, {id, "", true, true, nil},
		{"invalid", "", false, true, nil},
	} {
		got, err := setupScheduleArgs(tc.id, tc.digest, tc.resume, tc.interactive)
		if !reflect.DeepEqual(got, tc.want) || (err != nil) != (tc.want == nil) {
			t.Fatalf("args=%v err=%v", got, err)
		}
	}
}

func TestSetupSecondConsentCancellationStopsService(t *testing.T) {
	for _, answer := range []string{"\n", "no\n", "yes\n"} {
		var output bytes.Buffer
		installed := false
		err := runEnterpriseSetup(context.Background(), "registered", true, &output, setupActions{
			prepare: func() (string, error) { return "/fixture/stage", nil },
			confirm: func() error { return nil }, // Installation scope already confirmed.
			schedule: func() error {
				return confirmDisplayedSchedule(context.Background(), strings.NewReader(answer), &output)
			},
			install: func(string) error { installed = true; return nil },
		})
		accepted := answer == "yes\n"
		if installed != accepted || (err == nil) != accepted {
			t.Fatal("installation scope bypassed separate periodic consent")
		}
	}
}

func TestSetupCLIRejectsUnsignedReleaseBeforeRegistration(t *testing.T) {
	root := t.TempDir()
	stateDir := filepath.Join(root, "state")
	t.Setenv("SIQ_EDGE_STATE_DIR", stateDir)
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	p, err := installplan.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	p.TargetArch = runtime.GOARCH
	p.IssuedAt = time.Now().Add(-time.Minute).UTC().Format("2006-01-02T15:04:05Z")
	p.ExpiresAt = time.Now().Add(10 * time.Minute).UTC().Format("2006-01-02T15:04:05Z")
	raw, err = json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	planPath, releasePath := filepath.Join(root, "plan.json"), filepath.Join(root, "release.json")
	if os.WriteFile(planPath, raw, 0600) != nil || os.WriteFile(releasePath, []byte(`{}`), 0600) != nil {
		t.Fatal("fixture")
	}
	h := sha256.Sum256(raw)
	err = cmdSetupEnterprise(context.Background(), []string{"--plan", planPath, "--release", releasePath, "--bundle", root, "--staging-parent", root, "--tenant", p.TenantID, "--environment", p.EnvironmentID, "--control-plane", p.ControlPlaneOrigin, "--confirm-plan-sha256", hex.EncodeToString(h[:]), "--enrollment-code-stdin", "--start"})
	if err == nil || err.Error() != "enterprise_setup_failed_at_prepare" {
		t.Fatal("untrusted release passed setup gate")
	}
	if _, err := os.Stat(stateDir); !os.IsNotExist(err) {
		t.Fatal("untrusted release created device state")
	}
}

func TestEnterpriseSetupStopsAtFailure(t *testing.T) {
	for _, failure := range []string{"prepare", "register", "recover", "consent", "service"} {
		t.Run(failure, func(t *testing.T) {
			var calls []string
			var out bytes.Buffer
			step := func(name string) error {
				calls = append(calls, name)
				if name == failure {
					return errors.New("synthetic-sensitive-detail")
				}
				return nil
			}
			kind := "new"
			if failure == "recover" {
				kind = "pending"
			}
			err := runEnterpriseSetup(context.Background(), kind, true, &out, setupActions{
				prepare:  func() (string, error) { return "/fixture/stage", step("prepare") },
				register: func() error { return step("register") }, recover: func() error { return step("recover") }, confirm: func() error { return step("consent") }, install: func(string) error { return step("service") },
			})
			if err == nil || err.Error() != "enterprise_setup_failed_at_"+failure || calls[len(calls)-1] != failure {
				t.Fatal("failure boundary not preserved")
			}
			if strings.Contains(out.String(), "sensitive") || strings.Contains(out.String(), "service_active_only") {
				t.Fatal("failure leaked or claimed success")
			}
			if failure != "prepare" && !strings.Contains(out.String(), "/fixture/stage") {
				t.Fatal("resume path lost")
			}
		})
	}
}

type failedSetupOutput struct{}

func TestSetupCancellationStopsLaterPhasesAndKeepsProgress(t *testing.T) {
	for _, kind := range []string{"new", "pending", "registered"} {
		for _, cancelAt := range []string{"before", "prepare", "identity", "consent"} {
			if kind == "registered" && cancelAt == "identity" {
				continue
			}
			t.Run(kind+"_"+cancelAt, func(t *testing.T) {
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				var calls []string
				var out bytes.Buffer
				step := func(name string) error {
					if ctx.Err() != nil {
						t.Fatal("action ran after cancellation")
					}
					calls = append(calls, name)
					if name == cancelAt {
						cancel()
					}
					return nil
				}
				if cancelAt == "before" {
					cancel()
				}
				err := runEnterpriseSetup(ctx, kind, true, &out, setupActions{
					prepare:  func() (string, error) { return "/fixture/stage", step("prepare") },
					register: func() error { return step("identity") },
					recover:  func() error { return step("identity") },
					confirm:  func() error { return step("consent") },
					install:  func(string) error { t.Fatal("service activated after cancellation"); return nil },
				})
				if !errors.Is(err, context.Canceled) {
					t.Fatal("cancel not reported")
				}
				if cancelAt == "before" {
					if len(calls) != 0 || out.Len() != 0 {
						t.Fatal("pre-cancelled work ran")
					}
				} else if calls[len(calls)-1] != cancelAt || !strings.Contains(out.String(), "/fixture/stage") {
					t.Fatal("completed phase or resume location lost")
				}
			})
		}
	}
}

func (failedSetupOutput) Write([]byte) (int, error) { return 0, errors.New("synthetic-output-error") }

func TestEnterpriseSetupStopsWhenProgressCannotBeRecorded(t *testing.T) {
	called := false
	err := runEnterpriseSetup(context.Background(), "new", false, failedSetupOutput{}, setupActions{prepare: func() (string, error) { return "/fixture/stage", nil }, register: func() error { called = true; return nil }})
	if err == nil || called {
		t.Fatal("registration proceeded without recoverable progress")
	}
}

func TestSetupIdentityClassificationPreservesExistingState(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	if kind, err := setupIdentityKind("https://expected.test", "env-fixture"); err != nil || kind != "new" {
		t.Fatal("new classification")
	}
	if beginRegistration(&State{ControlPlaneURL: "https://expected.test", DeviceIdentity: "fixture", EnvironmentID: "env-fixture"}) != nil {
		t.Fatal("pending fixture")
	}
	if kind, err := setupIdentityKind("https://expected.test", "env-fixture"); err != nil || kind != "pending" {
		t.Fatal("pending classification")
	}
	if _, err := setupIdentityKind("https://expected.test", "other"); err == nil {
		t.Fatal("pending environment mismatch accepted")
	}
	state := &State{ControlPlaneURL: "https://expected.test", DeviceIdentity: "fixture", EnvironmentID: "env-fixture", Secret: "synthetic"}
	if state.Save() != nil {
		t.Fatal("registered fixture")
	}
	before, err := os.ReadFile(filepath.Join(dir, "state.json"))
	if err != nil {
		t.Fatal("read fixture")
	}
	if kind, err := setupIdentityKind("https://expected.test", "env-fixture"); err != nil || kind != "registered" {
		t.Fatal("registered classification")
	}
	if _, err := setupIdentityKind("https://other.test", "env-fixture"); err == nil {
		t.Fatal("existing origin mismatch accepted")
	}
	after, _ := os.ReadFile(filepath.Join(dir, "state.json"))
	if !bytes.Equal(before, after) {
		t.Fatal("classification changed identity")
	}
}
