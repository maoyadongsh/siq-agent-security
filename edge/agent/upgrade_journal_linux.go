//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"syscall"
	"time"

	"siq-agent-security/edge/agent/installplan"
)

const upgradePendingName = "enterprise-upgrade-pending.json"
const upgradeJournalLimit = 2 << 20

var errUpgradePending = errors.New("enterprise_upgrade_pending; preserve state and journal for explicit recovery")
var errUpgradeConflict = errors.New("enterprise_upgrade_conflicting_transaction; finish credential recovery or explicitly retire the old discovery schedule first")

// Private local recovery input, not a success receipt. It contains plan bytes
// and credential-binding hashes, never a copy of a device token or signing seed.
type upgradeJournal struct {
	Schema            string        `json:"schema_version"`
	Intent            upgradeIntent `json:"intent"`
	Confirmation      string        `json:"confirmation_sha256"`
	Baseline          string        `json:"state_baseline_sha256"`
	OriginalPlan      []byte        `json:"original_plan_bytes"`
	RestoredStateHash string        `json:"restored_state_sha256"`
	TargetStateHash   string        `json:"target_state_sha256"`
}

// Even an unreadable, partial or linked marker is a stop condition. Never try
// to repair it in an ordinary task or identity/consent mutation command.
func requireNoUpgradePending() error {
	dir, err := StateDir()
	if err != nil {
		return errUpgradePending
	}
	if _, err := os.Lstat(filepath.Join(dir, upgradePendingName)); !errors.Is(err, os.ErrNotExist) {
		return errUpgradePending
	}
	return nil
}

func requireNoUpgradeConflict() error {
	dir, err := StateDir()
	if err != nil {
		return errUpgradeConflict
	}
	for _, name := range []string{"credential-rotation-pending.json", scheduleJournalName,
		"discovery-schedule-confirmed.json", scheduleRetirementPendingName} {
		if _, err := os.Lstat(filepath.Join(dir, name)); !errors.Is(err, os.ErrNotExist) {
			return errUpgradeConflict
		}
	}
	return nil
}

func upgradeStateBaseline(state *State) string {
	copy := *state
	copy.DiscoveryPlan, copy.DiscoveryPlanSHA256 = nil, ""
	raw, err := json.Marshal(copy)
	if err != nil {
		return ""
	}
	return upgradeDigest(raw)
}

// Use exactly State.Save's encoding without ever writing or publishing its
// credential-bearing bytes. Return values stay in memory within the caller.
func upgradeStateBytes(state *State, plan []byte) ([]byte, error) {
	copy := *state
	copy.DiscoveryPlan = append(json.RawMessage(nil), plan...)
	var err error
	copy.DiscoveryPlanSHA256, err = compactPlanDigest(plan)
	if err != nil {
		return nil, errUpgradePending
	}
	raw, err := json.MarshalIndent(copy, "", "  ")
	if err != nil {
		return nil, errUpgradePending
	}
	return raw, nil
}

// Caller must hold the raw task lock through journal creation and all later
// mutations/recovery. The public CLI will use the fixed publisher verifier;
// this internal dependency exists only for component fault tests.
func prepareUpgradeJournal(ctx context.Context, o upgradeReviewOptions, confirmation string, now func() time.Time, verify upgradeStageVerifier) (*upgradeJournal, error) {
	if now == nil || verify == nil || requireNoUpgradePending() != nil || requireNoUpgradeConflict() != nil {
		return nil, errUpgradeConflict
	}
	review, err := inspectUpgrade(ctx, o, now, verify)
	if err != nil || confirmation != review.Confirmation {
		return nil, errUpgradePending
	}
	raw, err := readDeviceState(review.Intent.StatePath)
	var state State
	if err != nil || upgradeDigest(raw) != review.Intent.StateSHA256 || strictDiscoveryJSON(raw, &state) != nil {
		return nil, errUpgradePending
	}
	targetPlan, err := json.Marshal(review.Intent.To.Plan)
	if err != nil {
		return nil, errUpgradePending
	}
	restored, err := upgradeStateBytes(&state, state.DiscoveryPlan)
	if err != nil {
		return nil, err
	}
	target, err := upgradeStateBytes(&state, targetPlan)
	if err != nil {
		return nil, err
	}
	journal := &upgradeJournal{Schema: "enterprise-upgrade-pending/v1", Intent: review.Intent,
		Confirmation: confirmation, Baseline: upgradeStateBaseline(&state),
		OriginalPlan:      append([]byte(nil), state.DiscoveryPlan...),
		RestoredStateHash: upgradeDigest(restored), TargetStateHash: upgradeDigest(target)}
	if _, err := journal.inspect(ctx, verify); err != nil || requireNoUpgradeConflict() != nil ||
		review.Intent.To.Plan.RequireCurrent(now(), o.tenant, state.EnvironmentID, state.ControlPlaneURL, runtime.GOARCH) != nil {
		return nil, errUpgradePending
	}
	stateAgain, stateErr := readDeviceState(review.Intent.StatePath)
	unitAgain, unitErr := readUpgradeUnit(review.Intent.UnitPath)
	if stateErr != nil || unitErr != nil || !bytes.Equal(raw, stateAgain) || upgradeDigest(unitAgain) != review.Intent.From.UnitSHA256 {
		return nil, errUpgradePending
	}
	body, err := json.Marshal(journal)
	if err != nil || len(body) > upgradeJournalLimit || ctx.Err() != nil {
		return nil, errUpgradePending
	}
	dir, err := scheduleStateDirectory()
	if err != nil {
		return nil, errUpgradePending
	}
	defer dir.Close()
	fd, err := syscall.Openat(int(dir.Fd()), upgradePendingName, syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0600)
	if err != nil {
		return nil, errUpgradePending
	}
	file := os.NewFile(uintptr(fd), "upgrade-pending")
	n, writeErr := file.Write(body)
	syncErr := file.Sync()
	closeErr := file.Close()
	if writeErr != nil || n != len(body) || syncErr != nil || closeErr != nil || dir.Sync() != nil {
		return nil, errUpgradePending // Preserve even incomplete records for review.
	}
	stored, err := readUpgradeJournal(ctx, verify)
	if err != nil || !reflect.DeepEqual(stored, journal) {
		return nil, errUpgradePending
	}
	return stored, nil
}

func readUpgradeJournal(ctx context.Context, verify upgradeStageVerifier) (*upgradeJournal, error) {
	dir, err := StateDir()
	if err != nil {
		return nil, errUpgradePending
	}
	raw, err := readDeviceState(filepath.Join(dir, upgradePendingName))
	var journal upgradeJournal
	if err != nil || len(raw) > upgradeJournalLimit || strictDiscoveryJSON(raw, &journal) != nil {
		return nil, errUpgradePending
	}
	if _, err := journal.inspect(ctx, verify); err != nil {
		return nil, err
	}
	again, err := readDeviceState(filepath.Join(dir, upgradePendingName))
	if err != nil || !bytes.Equal(raw, again) {
		return nil, errUpgradePending
	}
	return &journal, nil
}

// Read-only recovery inspection. It accepts known intermediate pairs, never a
// third state/unit or changed identity. Applying the target additionally needs
// a current plan, a stopped service and explicit direction confirmation.
func (j *upgradeJournal) inspect(ctx context.Context, verify upgradeStageVerifier) (*State, error) {
	if j == nil || ctx.Err() != nil || verify == nil || j.Schema != "enterprise-upgrade-pending/v1" ||
		j.Intent.Schema != "enterprise-upgrade-intent/v1" || requireNoUpgradeConflict() != nil {
		return nil, errUpgradePending
	}
	i := j.Intent
	for _, value := range []string{i.StateSHA256, j.Baseline, j.Confirmation, j.RestoredStateHash, j.TargetStateHash} {
		decoded, err := hex.DecodeString(value)
		if err != nil || len(decoded) != 32 || strings.ToLower(value) != value {
			return nil, errUpgradePending
		}
	}
	confirmation, err := i.digest()
	if err != nil || confirmation != j.Confirmation {
		return nil, errUpgradePending
	}
	path, err := StateFilePath()
	config, configErr := os.UserConfigDir()
	if err != nil || configErr != nil || !canonicalUpgradePath(path) || path != i.StatePath ||
		i.UnitPath != filepath.Join(config, "systemd", "user", enterpriseUnitName) ||
		!canonicalUpgradePath(i.From.StagePath) || !canonicalUpgradePath(i.To.StagePath) ||
		i.From.StagePath == i.To.StagePath || strings.HasPrefix(i.From.StagePath, i.To.StagePath+"/") ||
		strings.HasPrefix(i.To.StagePath, i.From.StagePath+"/") {
		return nil, errUpgradePending
	}
	raw, err := readDeviceState(path)
	var state State
	if err != nil || strictDiscoveryJSON(raw, &state) != nil || state.Secret == "" || state.DeviceIdentity == "" ||
		state.DeviceIdentity != i.DeviceIdentity || state.EnvironmentID != i.EnvironmentID ||
		state.ControlPlaneURL != i.ControlPlaneOrigin || upgradeStateBaseline(&state) != j.Baseline {
		return nil, errUpgradePending
	}
	old, err := installplan.Parse(j.OriginalPlan)
	if err != nil || !reflect.DeepEqual(*old, i.From.Plan) {
		return nil, errUpgradePending
	}
	current, err := installplan.Parse(state.DiscoveryPlan)
	digest, digestErr := compactPlanDigest(state.DiscoveryPlan)
	if err != nil || digestErr != nil || digest != state.DiscoveryPlanSHA256 ||
		(!reflect.DeepEqual(*current, i.From.Plan) && !reflect.DeepEqual(*current, i.To.Plan)) {
		return nil, errUpgradePending
	}
	newPlan, err := json.Marshal(i.To.Plan)
	if err != nil {
		return nil, errUpgradePending
	}
	restored, restoredErr := upgradeStateBytes(&state, j.OriginalPlan)
	target, targetErr := upgradeStateBytes(&state, newPlan)
	hash := upgradeDigest(raw)
	if restoredErr != nil || targetErr != nil || upgradeDigest(restored) != j.RestoredStateHash ||
		upgradeDigest(target) != j.TargetStateHash ||
		(hash != i.StateSHA256 && hash != j.RestoredStateHash && hash != j.TargetStateHash) {
		return nil, errUpgradePending
	}
	// An original/restored hash always denotes the old plan; target denotes new.
	if (hash == j.TargetStateHash && !reflect.DeepEqual(*current, i.To.Plan)) ||
		(hash != j.TargetStateHash && !reflect.DeepEqual(*current, i.From.Plan)) {
		return nil, errUpgradePending
	}
	unit, err := readUpgradeUnit(i.UnitPath)
	if err != nil {
		return nil, errUpgradePending
	}
	matchedUnit := false
	for _, side := range []upgradeSide{i.From, i.To} {
		planRaw, err := json.Marshal(side.Plan)
		plan, parseErr := installplan.Parse(planRaw)
		if err != nil || parseErr != nil || plan.TenantID != i.TenantID || plan.EnvironmentID != i.EnvironmentID ||
			plan.ControlPlaneOrigin != i.ControlPlaneOrigin || plan.TargetOS != "linux" ||
			plan.TargetArch != runtime.GOARCH || plan.ServiceMode != "user" {
			return nil, errUpgradePending
		}
		expected, err := upgradeUnit(side.StagePath, filepath.Dir(path))
		if err != nil || upgradeDigest(expected) != side.UnitSHA256 {
			return nil, errUpgradePending
		}
		matchedUnit = matchedUnit || bytes.Equal(unit, expected)
		release, err := readInstallDocument(filepath.Join(side.StagePath, "release.json"))
		if err != nil || ctx.Err() != nil || verify(side.Plan, release, side.StagePath) != nil {
			return nil, errUpgradePending
		}
	}
	stateAgain, stateErr := readDeviceState(path)
	unitAgain, unitErr := readUpgradeUnit(i.UnitPath)
	if !matchedUnit || stateErr != nil || unitErr != nil || !bytes.Equal(raw, stateAgain) ||
		!bytes.Equal(unit, unitAgain) || ctx.Err() != nil || requireNoUpgradeConflict() != nil {
		return nil, errUpgradePending
	}
	return &state, nil
}
