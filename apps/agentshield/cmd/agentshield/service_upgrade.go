package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"time"
)

func cmdServiceUpgrade(args []string, out io.Writer) error {
	fs := flag.NewFlagSet("service-upgrade", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	manifest := fs.String("manifest", "", "signed v2 manifest")
	sourceManifest := fs.String("source-manifest", "", "optional signed prior release to preserve for rollback")
	binary := fs.String("binary", "", "candidate binary")
	confirm := fs.Bool("confirm-upgrade", false, "confirm interruption of protection")
	recoverID := fs.String("recover", "", "resume immutable transaction")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if runtime.GOOS != "linux" {
		return errors.New("service-upgrade: Linux user service integration required")
	}
	if !*confirm || *manifest == "" || *binary == "" || fs.NArg() != 0 {
		return errors.New("升级会短暂停止保护，block 模式下受控操作将被拒绝；请提供 --manifest FILE --binary FILE --confirm-upgrade")
	}
	if *recoverID != "" && *sourceManifest != "" {
		return errors.New("service-upgrade: source-manifest applies only to a new upgrade")
	}
	var source bytes.Buffer
	if err := cmdServiceUnit(nil, &source); err != nil {
		return err
	}
	version, err := clientrelease.CheckUpgrade(*manifest, *binary)
	if err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	staged, err := clientrelease.Stage(dir, *manifest, *binary)
	if err != nil {
		return err
	}
	staged, err = filepath.Abs(staged)
	if err == nil {
		staged, err = filepath.EvalSymlinks(staged)
	}
	if err != nil {
		return err
	}
	verifiedVersion, err := clientrelease.CheckUpgrade(*manifest, staged)
	if err != nil {
		return err
	}
	if verifiedVersion != version {
		return errors.New("service-upgrade: release changed during preparation")
	}
	canonicalDir, err := filepath.Abs(dir)
	if err == nil {
		canonicalDir, err = filepath.EvalSymlinks(canonicalDir)
	}
	if err != nil {
		return err
	}
	target, err := renderUserUnit(staged, canonicalDir)
	if err != nil {
		return err
	}
	st := &state.Store{Dir: canonicalDir}
	ready := func() error {
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
			return errors.New("service-upgrade: running version differs from verified release")
		}
		return nil
	}
	// Verification is repeated immediately before the irreversible stop request.
	recheck := func() error {
		v, err := clientrelease.CheckUpgrade(*manifest, staged)
		if err != nil {
			return err
		}
		if v != version {
			return errors.New("service-upgrade: candidate declaration changed")
		}
		return nil
	}
	var binaryCheck *serviceBinaryCheck
	if *recoverID == "" {
		preserved, err := clientrelease.SnapshotCurrent(st.Dir)
		if err != nil {
			return err
		}
		if *sourceManifest != "" {
			if _, err := clientrelease.CheckUpgrade(*sourceManifest, preserved); err != nil {
				return err
			}
			if _, err := clientrelease.Stage(st.Dir, *sourceManifest, preserved); err != nil {
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
		observedUnit, err := renderUserUnit(sourcePath, canonicalDir)
		if err != nil || observedUnit != source.String() {
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
		binaryCheck = &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: sourceHash, TargetSHA256: targetHash}, sourcePath: sourcePath, targetPath: staged}
		if _, err = fmt.Fprintf(out, "已留存当前 CLI 程序的本地副本：%s\n", preserved); err != nil {
			return err
		}
	}
	if *recoverID != "" {
		key, err := signing.LoadExisting(st.Dir)
		if err != nil {
			return err
		}
		plan, err := st.ReadServiceSwitch(key, *recoverID)
		if err != nil {
			return err
		}
		if plan.BinaryBindings != nil {
			binaryCheck = &serviceBinaryCheck{bindings: *plan.BinaryBindings, targetPath: staged}
		}
	}
	return upgradeUserService(st, source.Bytes(), []byte(target), *recoverID, out, runUserSystemctl, recheck, ready, binaryCheck)
}

func upgradeUserService(st *state.Store, source, target []byte, recoverID string, out io.Writer, control userSystemctl, recheck, ready func() error, checks ...*serviceBinaryCheck) error {
	return switchUserService(st, source, target, recoverID, out, control, recheck, ready, false, checks...)
}

func switchUserService(st *state.Store, source, target []byte, recoverID string, out io.Writer, control userSystemctl, recheck, ready func() error, rollback bool, checks ...*serviceBinaryCheck) (resultErr error) {
	var binaryCheck *serviceBinaryCheck
	if len(checks) > 1 {
		return errors.New("service-switch: ambiguous binary checks")
	}
	if len(checks) == 1 {
		binaryCheck = checks[0]
	}
	lifecycle, err := state.AcquireWriter(filepath.Join(st.Dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lifecycle.Release()) }()
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	id := recoverID
	defer func() {
		if resultErr != nil && id != "" {
			resultErr = fmt.Errorf("service-upgrade: transaction %s incomplete; retry with --recover %s: %w", id, id, resultErr)
		}
	}()
	var record state.UserServiceRecord
	if id != "" {
		plan, err := st.ReadServiceSwitch(key, id)
		if err != nil {
			return err
		}
		if !bytes.Equal(target, []byte(plan.TargetUnit)) {
			return errors.New("service-upgrade: recovery candidate differs from recorded target")
		}
		if plan.BinaryBindings != nil {
			if binaryCheck == nil || binaryCheck.bindings != *plan.BinaryBindings {
				return errors.New("service-switch: recovery binary bindings mismatch")
			}
		} else if binaryCheck != nil {
			return errors.New("service-switch: legacy journal has no binary bindings")
		}
		record = plan.SourceRecord
	} else {
		record, err = st.VerifyUserService(key, source)
		if err != nil {
			return err
		}
		if err = st.CheckServiceSwitchPending(); err != nil {
			return err
		}
	}
	props, err := readUserUnit(control, record.UnitName)
	if err != nil {
		return err
	}
	path := filepath.Join(st.Dir, record.UnitName)
	if err = verifyUserUnit(props, path, runtimeUserUnit(props)); err != nil {
		return err
	}
	if err = binaryCheck.target(); err != nil {
		return err
	}
	if id == "" {
		if err = binaryCheck.source(); err != nil {
			return err
		}
	}
	if err = recheck(); err != nil {
		return err
	}
	if id != "" && serviceRunning(props) {
		if err = st.CheckServiceSwitchPending(); err != nil {
			return err
		}
		if _, err = st.VerifyUserService(key, target); err != nil {
			return err
		}
		if err = ready(); err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, "目标版本已运行且健康，复用已完成的升级。")
		return err
	}
	if id == "" {
		if _, err = fmt.Fprintln(out, "正在停止保护并切换已校验候选；block 模式下受控操作将暂时被拒绝。"); err != nil {
			return err
		}
		if _, err = control("stop", "--", record.UnitName); err != nil {
			return err
		}
		props, err = readUserUnit(control, record.UnitName)
		if err != nil {
			return err
		}
	}
	if id == "" && !rollback {
		if err = serviceStopped(st, props); err != nil {
			return err
		}
	} else if err = serviceRecoveryQuiescent(props); err != nil {
		return err
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	err = func() (writeErr error) {
		defer func() { writeErr = errors.Join(writeErr, writer.Release()) }()
		if id == "" {
			if err = binaryCheck.source(); err != nil {
				return err
			}
			if err = binaryCheck.target(); err != nil {
				return err
			}
			if binaryCheck != nil {
				id, err = st.PrepareServiceSwitchWithBinaries(writer, key, source, target, binaryCheck.bindings)
			} else {
				id, err = st.PrepareServiceSwitch(writer, key, source, target)
			}
			if err != nil {
				return err
			}
			if _, err = fmt.Fprintf(out, "切换事务：%s\n", id); err != nil {
				return err
			}
		}
		return st.ApplyServiceSwitch(writer, key, id)
	}()
	if err != nil {
		return err
	}
	if err = recheck(); err != nil {
		return err
	}
	if _, err = control("daemon-reload"); err != nil {
		return err
	}
	props, err = readUserUnit(control, record.UnitName)
	if err != nil {
		return err
	}
	if err = verifyUserUnit(props, path, runtimeUserUnit(props)); err != nil {
		return err
	}
	if _, err = st.VerifyUserService(key, target); err != nil {
		return err
	}
	if err = binaryCheck.target(); err != nil {
		return err
	}
	if _, err = control("start", "--", record.UnitName); err != nil {
		return err
	}
	deadline := time.Now().Add(12 * time.Second)
	for {
		props, err = readUserUnit(control, record.UnitName)
		if err != nil {
			return err
		}
		if err = verifyUserUnit(props, path, runtimeUserUnit(props)); err != nil {
			return err
		}
		if serviceRunning(props) && ready() == nil {
			break
		}
		if props["ActiveState"] == "failed" || time.Now().After(deadline) {
			return errors.New("service-upgrade: target readiness not confirmed")
		}
		time.Sleep(100 * time.Millisecond)
	}
	_, err = fmt.Fprintln(out, "已切换到校验通过的目标版本，本实例 API 健康检查通过。")
	return err
}

// A failed start is not a normal stop. Recovery only needs an absent manager
// process, then AcquireWriter independently verifies state-writer ownership.
func serviceRecoveryQuiescent(props map[string]string) error {
	if (props["ActiveState"] != "inactive" && props["ActiveState"] != "failed") || props["MainPID"] != "0" {
		return errors.New("service-upgrade: recovery requires an inactive or failed unit with no main process")
	}
	return nil
}
