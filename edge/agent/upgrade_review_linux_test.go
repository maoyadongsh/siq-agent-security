//go:build linux

package main

import (
	"bytes"
	"context"
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

type upgradeFixture struct {
	o           upgradeReviewOptions
	now         time.Time
	state       *State
	root, unit  string
	old, next   installplan.Plan
	verifyCalls int
}

func newUpgradeFixture(t *testing.T) *upgradeFixture {
	t.Helper()
	root := privateUnitTemp(t)
	stateDir := filepath.Join(root, "state")
	config := filepath.Join(root, "config")
	t.Setenv("SIQ_EDGE_STATE_DIR", stateDir)
	t.Setenv("XDG_CONFIG_HOME", config)
	raw, err := os.ReadFile("installplan/testdata/plan.json")
	if err != nil {
		t.Fatal(err)
	}
	var plan installplan.Plan
	if json.Unmarshal(raw, &plan) != nil {
		t.Fatal("fixture plan")
	}
	now := time.Now().UTC().Truncate(time.Second)
	plan.TargetArch = runtime.GOARCH
	plan.IssuedAt = now.Add(-time.Hour).Format(time.RFC3339)
	plan.ExpiresAt = now.Add(-50 * time.Minute).Format(time.RFC3339)
	plan.ReleaseManifestSHA256 = upgradeDigest([]byte("old synthetic release"))
	raw, _ = json.Marshal(plan)
	digest, _ := compactPlanDigest(raw)
	state := &State{ControlPlaneURL: plan.ControlPlaneOrigin, EnvironmentID: plan.EnvironmentID,
		DeviceIdentity: "synthetic-device", Secret: "SYNTHETIC-PRIVATE-DEVICE-TOKEN",
		SignerSeed: "SYNTHETIC-PRIVATE-SEED", DiscoveryPlan: raw, DiscoveryPlanSHA256: digest}
	if state.Save() != nil {
		t.Fatal("fixture state")
	}
	f := &upgradeFixture{o: upgradeReviewOptions{from: filepath.Join(root, "old-stage"),
		to: filepath.Join(root, "new-stage"), plan: filepath.Join(root, "new-plan.json"), tenant: plan.TenantID},
		now: now, state: state, root: root, old: plan, next: plan,
		unit: filepath.Join(config, "systemd", "user", enterpriseUnitName)}
	f.next.PlanID = "eip-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	f.next.ReleaseVersion = "0.4.1-upgrade-fixture"
	f.next.Connectors = append([]installplan.Connector(nil), plan.Connectors...)
	for i := range f.next.Connectors {
		f.next.Connectors[i].Version = f.next.ReleaseVersion
	}
	f.next.Connectors[0].Scope.Roots = []string{"~/评估角色/*"}
	f.next.IssuedAt = now.Add(-time.Minute).Format(time.RFC3339)
	f.next.ExpiresAt = now.Add(10 * time.Minute).Format(time.RFC3339)
	f.next.ReleaseManifestSHA256 = upgradeDigest([]byte("new synthetic release"))
	f.savePlan(t)
	for stage, body := range map[string]string{f.o.from: "old synthetic release", f.o.to: "new synthetic release"} {
		if os.Mkdir(stage, 0700) != nil || os.WriteFile(filepath.Join(stage, "release.json"), []byte(body), 0400) != nil {
			t.Fatal("fixture stage")
		}
	}
	unit, err := upgradeUnit(f.o.from, stateDir)
	if err != nil || writeUserUnit(filepath.Dir(f.unit), unit) != nil {
		t.Fatal("fixture unit")
	}
	return f
}

func (f *upgradeFixture) savePlan(t *testing.T) {
	t.Helper()
	raw, err := json.Marshal(f.next)
	if err != nil || os.WriteFile(f.o.plan, raw, 0600) != nil {
		t.Fatal("fixture plan write")
	}
}

func (f *upgradeFixture) verifier(plan installplan.Plan, raw []byte, stage string) error {
	f.verifyCalls++
	if upgradeDigest(raw) != plan.ReleaseManifestSHA256 || (stage != f.o.from && stage != f.o.to) {
		return errors.New("synthetic verifier binding rejected")
	}
	return nil // Explicit component double, not publisher signature verification.
}

func upgradeTree(t *testing.T, root string) map[string]string {
	t.Helper()
	files := map[string]string{}
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if !info.IsDir() && info.Mode().IsRegular() {
			raw, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			files[path] = upgradeDigest(raw) + ":" + info.Mode().String()
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return files
}

func TestUpgradeReviewBindsBothVersionsWithoutWritingOrLeaking(t *testing.T) {
	f := newUpgradeFixture(t)
	before := upgradeTree(t, f.root)
	review, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil || f.verifyCalls != 4 {
		t.Fatalf("review failed: %v, calls=%d", err, f.verifyCalls)
	}
	raw, _ := json.Marshal(review)
	if bytes.Contains(raw, []byte(f.state.Secret)) || bytes.Contains(raw, []byte(f.state.SignerSeed)) ||
		review.Installed || review.BusinessPermissions || review.CapabilitiesVerified ||
		!review.SignatureVerified || !review.RequiresConfirmation || review.ServiceActivity != "not_checked" {
		t.Fatal("review confused identity/protection/installation facts")
	}
	if review.Intent.From.Plan.PlanID != f.old.PlanID || review.Intent.To.Plan.PlanID != f.next.PlanID ||
		review.Intent.From.UnitSHA256 == review.Intent.To.UnitSHA256 || len(review.Confirmation) != 64 {
		t.Fatal("old/new inputs not fully bound")
	}
	if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
		t.Fatal("read-only review changed installation")
	}
	// Optional wire sample remains an explicitly synthetic component fixture.
	if path := os.Getenv("SIQ_UPGRADE_REVIEW_WIRE_SAMPLE"); path != "" {
		if os.WriteFile(path, append(raw, '\n'), 0600) != nil {
			t.Fatal("wire sample output")
		}
	}
}

func TestUpgradeReviewRejectsWrongTargetAndUntrustedUnit(t *testing.T) {
	for _, name := range []string{"tenant", "environment", "origin", "arch", "mode", "expired", "future",
		"same_stage", "nested_stage", "relative_stage", "alias_stage", "bad_old_digest", "custom_unit",
		"writable_unit", "writable_parent", "unit_symlink", "state_symlink", "unknown_state", "bad_plan"} {
		t.Run(name, func(t *testing.T) {
			f := newUpgradeFixture(t)
			switch name {
			case "tenant":
				f.next.TenantID = "other-tenant"
			case "environment":
				f.next.EnvironmentID = "other-environment"
			case "origin":
				f.next.ControlPlaneOrigin = "https://other.example.invalid"
			case "arch":
				f.next.TargetArch = "amd64"
				if runtime.GOARCH == "amd64" {
					f.next.TargetArch = "arm64"
				}
			case "mode":
				f.next.ServiceMode = "system"
			case "expired":
				f.next.IssuedAt, f.next.ExpiresAt = f.old.IssuedAt, f.old.ExpiresAt
			case "future":
				f.next.IssuedAt = f.now.Add(time.Minute).Format(time.RFC3339)
			case "same_stage":
				f.o.to = f.o.from
			case "nested_stage":
				f.o.to = filepath.Join(f.o.from, "nested")
			case "relative_stage":
				f.o.to = "relative"
			case "alias_stage":
				f.o.to += "/../new-stage"
			case "bad_old_digest":
				f.state.DiscoveryPlanSHA256 = strings.Repeat("0", 64)
				if f.state.Save() != nil {
					t.Fatal("fixture")
				}
			case "custom_unit":
				if os.WriteFile(f.unit, []byte("operator custom config"), 0600) != nil {
					t.Fatal("fixture")
				}
			case "writable_unit":
				if os.Chmod(f.unit, 0620) != nil {
					t.Fatal("fixture")
				}
			case "writable_parent":
				if os.Chmod(filepath.Dir(f.unit), 0770) != nil {
					t.Fatal("fixture")
				}
			case "unit_symlink":
				if os.Rename(f.unit, f.unit+".original") != nil || os.Symlink(f.unit+".original", f.unit) != nil {
					t.Fatal("fixture")
				}
			case "state_symlink":
				p, _ := StateFilePath()
				if os.Rename(p, p+".original") != nil || os.Symlink(p+".original", p) != nil {
					t.Fatal("fixture")
				}
			case "unknown_state":
				p, _ := StateFilePath()
				raw, _ := os.ReadFile(p)
				if os.WriteFile(p, append([]byte(`{"unknown":true,`), raw[1:]...), 0600) != nil {
					t.Fatal("fixture")
				}
			}
			f.savePlan(t)
			if name == "bad_plan" {
				if os.WriteFile(f.o.plan, []byte("null"), 0600) != nil {
					t.Fatal("fixture")
				}
			}
			before := upgradeTree(t, f.root)
			if _, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier); err == nil {
				t.Fatal("unsafe upgrade review accepted")
			}
			if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
				t.Fatal("failed review mutated files")
			}
		})
	}
}

func TestUpgradeReviewRechecksMutationExpiryAndCancellation(t *testing.T) {
	for _, fault := range []string{"state", "plan", "unit", "expiry", "cancel", "signature"} {
		t.Run(fault, func(t *testing.T) {
			f := newUpgradeFixture(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			now := f.now
			verify := func(p installplan.Plan, raw []byte, stage string) error {
				if err := f.verifier(p, raw, stage); err != nil {
					return err
				}
				if f.verifyCalls == 2 {
					switch fault {
					case "state":
						f.state.Secret += "-rotated"
						if f.state.Save() != nil {
							t.Fatal("fixture")
						}
					case "plan":
						file, err := os.OpenFile(f.o.plan, os.O_APPEND|os.O_WRONLY, 0600)
						if err != nil {
							t.Fatal(err)
						}
						_, err = file.WriteString("\n")
						file.Close()
						if err != nil {
							t.Fatal(err)
						}
					case "unit":
						if os.WriteFile(f.unit, []byte("operator replacement"), 0600) != nil {
							t.Fatal("fixture")
						}
					case "expiry":
						now = now.Add(time.Hour)
					case "cancel":
						cancel()
					case "signature":
						return errors.New("synthetic signature rejection")
					}
				}
				return nil
			}
			if _, err := inspectUpgrade(ctx, f.o, func() time.Time { return now }, verify); err == nil {
				t.Fatal("drift accepted")
			}
			if _, err := os.Stat(filepath.Join(filepath.Dir(f.unit), ".siq-unit.tmp")); !os.IsNotExist(err) {
				t.Fatal("review wrote file")
			}
		})
	}
}

func TestUpgradeReviewCLIUsesPinnedVerifierAndEmitsNoPartialResult(t *testing.T) {
	f := newUpgradeFixture(t)
	before := upgradeTree(t, f.root)
	var out bytes.Buffer
	err := reviewEnterpriseUpgrade(context.Background(), []string{"--plan", f.o.plan, "--from-stage", f.o.from,
		"--to-stage", f.o.to, "--tenant", f.o.tenant}, &out)
	if err == nil || out.Len() != 0 || !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
		t.Fatal("CLI accepted synthetic unsigned stage or changed installation")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if reviewEnterpriseUpgrade(ctx, nil, &out) == nil || out.Len() != 0 {
		t.Fatal("cancelled review emitted success")
	}
}

func TestUpgradeIntentDigestChangesForEveryBoundField(t *testing.T) {
	f := newUpgradeFixture(t)
	r, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	for _, change := range []func(*upgradeIntent){
		func(i *upgradeIntent) { i.DeviceIdentity += "x" }, func(i *upgradeIntent) { i.TenantID += "x" },
		func(i *upgradeIntent) { i.EnvironmentID += "x" }, func(i *upgradeIntent) { i.ControlPlaneOrigin += "x" },
		func(i *upgradeIntent) { i.StatePath += "x" }, func(i *upgradeIntent) { i.StateSHA256 = strings.Repeat("0", 64) },
		func(i *upgradeIntent) { i.UnitPath += "x" }, func(i *upgradeIntent) { i.From.StagePath += "x" },
		func(i *upgradeIntent) { i.To.StagePath += "x" }, func(i *upgradeIntent) { i.From.UnitSHA256 = strings.Repeat("0", 64) },
		func(i *upgradeIntent) { i.To.UnitSHA256 = strings.Repeat("0", 64) },
		func(i *upgradeIntent) { i.From.Plan.ReleaseVersion += "x" }, func(i *upgradeIntent) { i.To.Plan.ReleaseVersion += "x" },
	} {
		copy := r.Intent
		change(&copy)
		digest, err := copy.digest()
		if err != nil || digest == r.Confirmation {
			t.Fatal("intent field missing from digest")
		}
	}
}

type shortUpgradeWriter struct{}

func (shortUpgradeWriter) Write(p []byte) (int, error) { return len(p) / 2, nil }

func TestUpgradeReviewOutputFailureAndCancellationAreNotSuccess(t *testing.T) {
	f := newUpgradeFixture(t)
	r, err := inspectUpgrade(context.Background(), f.o, func() time.Time { return f.now }, f.verifier)
	if err != nil {
		t.Fatal(err)
	}
	before := upgradeTree(t, f.root)
	if emitUpgradeReview(context.Background(), r, shortUpgradeWriter{}) != errUpgradeReview {
		t.Fatal("short output accepted")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var out bytes.Buffer
	if emitUpgradeReview(ctx, r, &out) != errUpgradeReview || out.Len() != 0 {
		t.Fatal("cancelled output accepted")
	}
	if !reflect.DeepEqual(before, upgradeTree(t, f.root)) {
		t.Fatal("output failure changed installation")
	}
}
