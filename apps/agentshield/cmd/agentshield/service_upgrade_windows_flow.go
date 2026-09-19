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

// cmdServiceUpgradeWindows uses signed Task Scheduler ownership for Windows.
func cmdServiceUpgradeWindows(manifest, sourceManifest, binary, recoverID string, out io.Writer) error {
	var source bytes.Buffer

	canonicalDir, staged, version, err := stageVerifiedCandidate(manifest, binary)
	if err != nil {
		return err
	}
	st := &state.Store{Dir: canonicalDir}
	host, err := currentWindowsTaskSwitchHost()
	if err != nil {
		return err
	}
	instance, err := st.ReadLocalInstance()
	if err != nil {
		return err
	}
	target, err := renderWindowsTask(staged, canonicalDir, instance.InstanceID, host.sid)
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
		if err := cmdTaskXML(nil, &source); err != nil {
			return err
		}
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
		observed, err := renderWindowsTask(sourcePath, canonicalDir, instance.InstanceID, host.sid)
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
		plan, err := st.ReadWindowsTaskSwitch(key, recoverID)
		if err != nil {
			return err
		}
		source.WriteString(plan.SourceXML)
		check = &serviceBinaryCheck{bindings: plan.BinaryBindings, targetPath: staged}
	}

	return switchWindowsTask(st, host, source.Bytes(), []byte(target), recoverID, out, recheck, versionReady(st, version, "service-upgrade"), check)
}

// cmdServiceRollbackWindows restores the recorded source task and program.
func cmdServiceRollbackWindows(original, manifest, binary string, restore bool, recoverID string, out io.Writer) error {
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
	host, err := currentWindowsTaskSwitchHost()
	if err != nil {
		return err
	}
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadWindowsTaskSwitch(key, original)
	if err != nil {
		return err
	}
	if recoverID == "" {
		if err = st.CheckWindowsTaskSwitchCompleted(key, original); err != nil {
			return err
		}
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
	render := func(path string) (string, error) {
		return renderWindowsTask(path, st.Dir, instance.InstanceID, host.sid)
	}
	oldPath, version, err := prepareHistoricalBinary(st, plan.BinaryBindings, plan.SourceXML, render, binary, manifest, restore, checkUpgradeForCurrentState)
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

	return rollbackWindowsTask(st, host, original, []byte(plan.SourceXML), recoverID, out, recheck, versionReady(st, version, "service-rollback"), check)
}
