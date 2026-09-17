package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

// stageVerifiedCandidate verifies, stages and re-verifies a release candidate
// against the current state directory. It never executes the candidate.
func stageVerifiedCandidate(manifest, binary string) (string, string, string, error) {
	version, err := checkUpgradeForCurrentState(manifest, binary)
	if err != nil {
		return "", "", "", err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return "", "", "", err
	}
	staged, err := clientrelease.Stage(dir, manifest, binary)
	if err != nil {
		return "", "", "", err
	}
	staged, err = filepath.Abs(staged)
	if err == nil {
		staged, err = filepath.EvalSymlinks(staged)
	}
	if err != nil {
		return "", "", "", err
	}
	verifiedVersion, err := checkUpgradeForCurrentState(manifest, staged)
	if err != nil {
		return "", "", "", err
	}
	if verifiedVersion != version {
		return "", "", "", errors.New("service-upgrade: release changed during preparation")
	}
	canonicalDir, err := filepath.Abs(dir)
	if err == nil {
		canonicalDir, err = filepath.EvalSymlinks(canonicalDir)
	}
	if err != nil {
		return "", "", "", err
	}
	return canonicalDir, staged, version, nil
}

func versionReady(st *state.Store, version, command string) func() error {
	return func() error {
		cfg, err := st.LoadConfig()
		if err != nil {
			return err
		}
		client := localClient()
		defer client.CloseIdleConnections()
		health, err := probeLocalInstance(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st)
		if err != nil {
			return err
		}
		if health.Version != version {
			return errors.New(command + ": running version differs from verified release")
		}
		return nil
	}
}

// cmdServiceUpgradeDarwin mirrors the Linux flow with launchd as the manager.
func cmdServiceUpgradeDarwin(manifest, sourceManifest, binary, recoverID string, out io.Writer) error {
	var source bytes.Buffer
	if err := cmdLaunchAgentPlist(nil, &source); err != nil {
		return err
	}
	canonicalDir, staged, version, err := stageVerifiedCandidate(manifest, binary)
	if err != nil {
		return err
	}
	st := &state.Store{Dir: canonicalDir}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		return err
	}
	target, err := renderLaunchAgent(staged, canonicalDir, instance.InstanceID)
	if err != nil {
		return err
	}
	recheck := func() error {
		v, err := checkUpgradeForCurrentState(manifest, staged)
		if err != nil {
			return err
		}
		if v != version {
			return errors.New("service-upgrade: candidate declaration changed")
		}
		return nil
	}
	var check *serviceBinaryCheck
	if recoverID == "" {
		preserved, err := clientrelease.SnapshotCurrent(st.Dir)
		if err != nil {
			return err
		}
		if sourceManifest != "" {
			if _, err := checkUpgradeForCurrentState(sourceManifest, preserved); err != nil {
				return err
			}
			if _, err := clientrelease.Stage(st.Dir, sourceManifest, preserved); err != nil {
				return err
			}
		}
		sourcePath, err := os.Executable()
		if err == nil {
			sourcePath, err = filepath.EvalSymlinks(sourcePath)
		}
		if err != nil {
			return err
		}
		observed, err := renderLaunchAgent(sourcePath, canonicalDir, instance.InstanceID)
		if err != nil || observed != source.String() {
			return errors.New("service-upgrade: source executable location changed")
		}
		sourceHash, err := clientrelease.Digest(preserved)
		if err != nil {
			return err
		}
		targetHash, err := clientrelease.Digest(staged)
		if err != nil {
			return err
		}
		check = &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: sourceHash, TargetSHA256: targetHash}, sourcePath: sourcePath, targetPath: staged}
		if _, err = fmt.Fprintf(out, "已留存当前 CLI 程序的本地副本：%s\n", preserved); err != nil {
			return err
		}
	} else {
		key, err := signing.LoadExisting(st.Dir)
		if err != nil {
			return err
		}
		plan, err := st.ReadLaunchAgentSwitch(key, recoverID)
		if err != nil {
			return err
		}
		check = &serviceBinaryCheck{bindings: plan.BinaryBindings, targetPath: staged}
	}
	host, err := currentLaunchAgentHost()
	if err != nil {
		return err
	}
	return switchLaunchAgent(st, host, source.Bytes(), []byte(target), recoverID, out, recheck, versionReady(st, version, "service-upgrade"), false, check)
}

// cmdServiceRollbackDarwin restores the recorded source plist and program.
func cmdServiceRollbackDarwin(original, manifest, binary string, restore bool, recoverID string, out io.Writer) error {
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	dir, err = filepath.Abs(dir)
	if err == nil {
		dir, err = filepath.EvalSymlinks(dir)
	}
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadLaunchAgentSwitch(key, original)
	if err != nil {
		return err
	}
	if manifest == "" {
		candidate := binary
		if _, statErr := os.Lstat(candidate); errors.Is(statErr, os.ErrNotExist) && restore {
			candidate, err = clientrelease.SnapshotPath(st.Dir, plan.BinaryBindings.SourceSHA256)
			if err != nil {
				return err
			}
		}
		manifest, err = clientrelease.RetainedManifest(st.Dir, plan.BinaryBindings.SourceSHA256, candidate)
		if err != nil {
			return err
		}
	}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		return err
	}
	render := func(path string) (string, error) { return renderLaunchAgent(path, st.Dir, instance.InstanceID) }
	oldPath, version, err := prepareHistoricalBinary(st, plan.BinaryBindings, plan.SourcePlist, render, binary, manifest, restore, checkUpgradeForCurrentState)
	if err != nil {
		return err
	}
	recheck := func() error {
		v, err := checkUpgradeForCurrentState(manifest, oldPath)
		if err != nil {
			return err
		}
		if v != version {
			return errors.New("service-rollback: prior release changed")
		}
		return nil
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: plan.BinaryBindings.TargetSHA256, TargetSHA256: plan.BinaryBindings.SourceSHA256}, targetPath: oldPath}
	host, err := currentLaunchAgentHost()
	if err != nil {
		return err
	}
	return rollbackLaunchAgent(st, host, original, []byte(plan.SourcePlist), recoverID, out, recheck, versionReady(st, version, "service-rollback"), check)
}
