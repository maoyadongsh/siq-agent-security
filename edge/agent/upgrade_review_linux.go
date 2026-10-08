//go:build linux

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/installplan"
)

var errUpgradeReview = errors.New("enterprise_upgrade_review_failed; preserve installed state and verify both signed stages and current plan")
var errUpgradeUnit = errors.New("enterprise_upgrade_existing_unit_mismatch; preserve user configuration")
var errUpgradeWindow = errors.New("enterprise_upgrade_new_plan_outside_window; obtain a current plan without changing installed state")

type upgradeSide struct {
	StagePath  string           `json:"stage_path"`
	Plan       installplan.Plan `json:"plan"`
	UnitSHA256 string           `json:"unit_sha256"`
}

type upgradeIntent struct {
	Schema             string      `json:"schema_version"`
	DeviceIdentity     string      `json:"device_identity"`
	TenantID           string      `json:"tenant_id"`
	EnvironmentID      string      `json:"environment_id"`
	ControlPlaneOrigin string      `json:"control_plane_origin"`
	StatePath          string      `json:"state_path"`
	StateSHA256        string      `json:"state_file_sha256"`
	UnitPath           string      `json:"unit_path"`
	From               upgradeSide `json:"from"`
	To                 upgradeSide `json:"to"`
}

type upgradeReview struct {
	Schema               string        `json:"schema_version"`
	Status               string        `json:"status"`
	Intent               upgradeIntent `json:"intent"`
	Confirmation         string        `json:"confirmation_sha256"`
	SignatureVerified    bool          `json:"publisher_signature_verified"`
	ServiceActivity      string        `json:"service_activity"`
	CapabilitiesVerified bool          `json:"connector_capabilities_verified"`
	RequiresConfirmation bool          `json:"requires_explicit_confirmation"`
	Installed            bool          `json:"installed"`
	BusinessPermissions  bool          `json:"business_permissions_granted"`
}

type upgradeReviewOptions struct{ plan, from, to, tenant string }
type upgradeStageVerifier func(installplan.Plan, []byte, string) error

func upgradeDigest(raw []byte) string {
	h := sha256.Sum256(raw)
	return hex.EncodeToString(h[:])
}

func (intent upgradeIntent) digest() (string, error) {
	raw, err := json.Marshal(intent)
	if err != nil {
		return "", errUpgradeReview
	}
	value, err := canon.Decode(raw)
	if err != nil {
		return "", errUpgradeReview
	}
	raw, err = canon.Marshal(value)
	if err != nil {
		return "", errUpgradeReview
	}
	return upgradeDigest(raw), nil
}

// The CLI always uses the pinned publisher verifier. Injection stays private to
// component tests; there is no flag, environment variable or alternate key.
func inspectUpgrade(ctx context.Context, o upgradeReviewOptions, now func() time.Time, verify upgradeStageVerifier) (*upgradeReview, error) {
	if ctx.Err() != nil || o.tenant == "" || !canonicalUpgradePath(o.from) || !canonicalUpgradePath(o.to) ||
		o.from == o.to || strings.HasPrefix(o.from, o.to+"/") || strings.HasPrefix(o.to, o.from+"/") {
		return nil, errUpgradeReview
	}
	statePath, err := StateFilePath()
	if err != nil || !canonicalUpgradePath(statePath) {
		return nil, errUpgradeReview
	}
	stateRaw, err := readDeviceState(statePath)
	var state State
	if err != nil || strictDiscoveryJSON(stateRaw, &state) != nil || state.DeviceIdentity == "" || state.Secret == "" {
		return nil, errUpgradeReview
	}
	old, err := installplan.Parse(state.DiscoveryPlan)
	if err != nil {
		return nil, errUpgradeReview
	}
	digest, err := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digest != state.DiscoveryPlanSHA256 {
		return nil, errUpgradeReview
	}
	newRaw, err := readInstallDocument(o.plan)
	if err != nil {
		return nil, errUpgradeReview
	}
	next, err := installplan.Parse(newRaw)
	if err != nil {
		return nil, errUpgradeReview
	}
	for _, plan := range []*installplan.Plan{old, next} {
		if plan.TenantID != o.tenant || plan.EnvironmentID != state.EnvironmentID ||
			plan.ControlPlaneOrigin != state.ControlPlaneURL || plan.TargetArch != runtime.GOARCH ||
			plan.TargetOS != "linux" || plan.ServiceMode != "user" {
			return nil, errUpgradeReview
		}
	}
	if next.RequireCurrent(now(), o.tenant, state.EnvironmentID, state.ControlPlaneURL, runtime.GOARCH) != nil {
		return nil, errUpgradeWindow
	}
	config, err := os.UserConfigDir()
	if err != nil {
		return nil, errUpgradeReview
	}
	unitPath := filepath.Join(config, "systemd", "user", enterpriseUnitName)
	oldUnit, err := upgradeUnit(o.from, filepath.Dir(statePath))
	if err != nil {
		return nil, errUpgradeReview
	}
	newUnit, err := upgradeUnit(o.to, filepath.Dir(statePath))
	if err != nil {
		return nil, errUpgradeReview
	}
	actual, err := readUpgradeUnit(unitPath)
	if err != nil || !bytes.Equal(actual, oldUnit) {
		return nil, errUpgradeUnit
	}
	for pass := 0; pass < 2; pass++ {
		for _, source := range []struct {
			stage string
			plan  *installplan.Plan
		}{{o.from, old}, {o.to, next}} {
			if ctx.Err() != nil {
				return nil, errUpgradeReview
			}
			raw, err := readInstallDocument(filepath.Join(source.stage, "release.json"))
			if err != nil || verify(*source.plan, raw, source.stage) != nil {
				return nil, errUpgradeReview
			}
		}
	}
	// Re-read every mutable authority input. A review never repairs an input.
	stateAgain, err := readDeviceState(statePath)
	if err != nil || !bytes.Equal(stateRaw, stateAgain) {
		return nil, errUpgradeReview
	}
	planAgain, err := readInstallDocument(o.plan)
	if err != nil || !bytes.Equal(newRaw, planAgain) {
		return nil, errUpgradeReview
	}
	unitAgain, err := readUpgradeUnit(unitPath)
	if err != nil || !bytes.Equal(actual, unitAgain) {
		return nil, errUpgradeUnit
	}
	if ctx.Err() != nil {
		return nil, errUpgradeReview
	}
	if next.RequireCurrent(now(), o.tenant, state.EnvironmentID, state.ControlPlaneURL, runtime.GOARCH) != nil {
		return nil, errUpgradeWindow
	}
	intent := upgradeIntent{Schema: "enterprise-upgrade-intent/v1", DeviceIdentity: state.DeviceIdentity,
		TenantID: o.tenant, EnvironmentID: state.EnvironmentID, ControlPlaneOrigin: state.ControlPlaneURL,
		StatePath: statePath, StateSHA256: upgradeDigest(stateRaw), UnitPath: unitPath,
		From: upgradeSide{o.from, *old, upgradeDigest(oldUnit)}, To: upgradeSide{o.to, *next, upgradeDigest(newUnit)}}
	confirmation, err := intent.digest()
	if err != nil {
		return nil, err
	}
	return &upgradeReview{Schema: "enterprise-upgrade-review/v1", Status: "reviewed_not_applied", Intent: intent,
		Confirmation: confirmation, SignatureVerified: true, ServiceActivity: "not_checked", RequiresConfirmation: true}, nil
}

func canonicalUpgradePath(path string) bool {
	return len(path) <= 4096 && filepath.IsAbs(path) && filepath.Clean(path) == path && path != "/"
}

func upgradeUnit(stage, stateDir string) ([]byte, error) {
	dir := filepath.Join(stage, "bin", runtime.GOARCH)
	body, err := renderUserService(filepath.Join(dir, "edge-agent"), stateDir, dir)
	return []byte(body), err
}

func readUpgradeUnit(path string) ([]byte, error) {
	if !canonicalUpgradePath(path) {
		return nil, errUpgradeUnit
	}
	fd, err := syscall.Open("/", syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errUpgradeUnit
	}
	defer func() { syscall.Close(fd) }()
	for _, part := range strings.Split(strings.TrimPrefix(filepath.Dir(path), "/"), "/") {
		next, err := syscall.Openat(fd, part, syscall.O_RDONLY|syscall.O_DIRECTORY|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
		if err != nil {
			return nil, errUpgradeUnit
		}
		syscall.Close(fd)
		fd = next
		var st syscall.Stat_t
		if syscall.Fstat(fd, &st) != nil || (int(st.Uid) != os.Geteuid() && st.Uid != 0) ||
			(st.Mode&0022 != 0 && !(st.Uid == 0 && st.Mode&syscall.S_ISVTX != 0)) {
			return nil, errUpgradeUnit
		}
	}
	var parent syscall.Stat_t
	if syscall.Fstat(fd, &parent) != nil || int(parent.Uid) != os.Geteuid() {
		return nil, errUpgradeUnit
	}
	leaf, err := syscall.Openat(fd, filepath.Base(path), syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, errUpgradeUnit
	}
	f := os.NewFile(uintptr(leaf), "upgrade-unit")
	defer f.Close()
	var before, after syscall.Stat_t
	if syscall.Fstat(leaf, &before) != nil || before.Mode&syscall.S_IFMT != syscall.S_IFREG ||
		before.Nlink != 1 || int(before.Uid) != os.Geteuid() || before.Mode&0022 != 0 || before.Size > 65536 {
		return nil, errUpgradeUnit
	}
	raw, err := io.ReadAll(io.LimitReader(f, 65537))
	if err != nil || len(raw) > 65536 || syscall.Fstat(leaf, &after) != nil || !sameConnectorStat(before, after) {
		return nil, errUpgradeUnit
	}
	return raw, nil
}

func reviewEnterpriseUpgrade(ctx context.Context, args []string, output io.Writer) error {
	var o upgradeReviewOptions
	fs := flag.NewFlagSet("review-enterprise-upgrade", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&o.plan, "plan", "", "")
	fs.StringVar(&o.from, "from-stage", "", "")
	fs.StringVar(&o.to, "to-stage", "", "")
	fs.StringVar(&o.tenant, "tenant", "", "")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			_, err = io.WriteString(output, "review-enterprise-upgrade --plan FILE --from-stage DIR --to-stage DIR --tenant ID\nRead-only signed-source and scope review; does not stop, upgrade or start a service.\n")
			return err
		}
		return errUpgradeReview
	}
	if fs.NArg() != 0 {
		return errUpgradeReview
	}
	review, err := inspectUpgrade(ctx, o, time.Now, installplan.VerifyStagedBundle)
	if err != nil {
		return err
	}
	return emitUpgradeReview(ctx, review, output)
}

func emitUpgradeReview(ctx context.Context, review *upgradeReview, output io.Writer) error {
	raw, err := json.MarshalIndent(review, "", "  ")
	if err != nil || ctx.Err() != nil {
		return errUpgradeReview
	}
	raw = append(raw, '\n')
	if n, err := output.Write(raw); err != nil || n != len(raw) {
		return errUpgradeReview
	}
	return nil
}

func cmdReviewEnterpriseUpgrade(ctx context.Context, args []string) error {
	return reviewEnterpriseUpgrade(ctx, args, os.Stdout)
}
