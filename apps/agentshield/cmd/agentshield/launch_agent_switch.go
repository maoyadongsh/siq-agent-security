package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"time"
)

// launchAgentSwitchHost carries the launchd session the switch operates in.
type launchAgentSwitchHost struct {
	home    string
	uid     int
	control userSystemctl
}

// switchLaunchAgent is the macOS counterpart of switchUserService: it stops a
// verified source job, journals and applies the plist pair, then re-bootstraps
// the same registration link so launchd observes the new program.
func switchLaunchAgent(st *state.Store, host launchAgentSwitchHost, source, target []byte, recoverID string, out io.Writer, recheck, ready func() error, rollback bool, check *serviceBinaryCheck) (resultErr error) {
	if check == nil {
		return errors.New("launch-agent-switch: binary bindings required")
	}
	lifecycle, err := state.AcquireScopedWriter(st.Dir, "service-control")
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
	var record state.LaunchAgentRecord
	if id != "" {
		plan, err := st.ReadLaunchAgentSwitch(key, id)
		if err != nil {
			return err
		}
		if !bytes.Equal(target, []byte(plan.TargetPlist)) || !bytes.Equal(source, []byte(plan.SourcePlist)) {
			return errors.New("service-upgrade: recovery candidate differs from recorded target")
		}
		if check.bindings != plan.BinaryBindings {
			return errors.New("service-switch: recovery binary bindings mismatch")
		}
		record = plan.SourceRecord
	} else {
		record, err = st.VerifyLaunchAgent(key, source)
		if err != nil {
			return err
		}
		if err = st.CheckServiceSwitchPending(); err != nil {
			return err
		}
	}
	label := record.Label
	sourceFile, err := launchAgentSource(st.Dir, label)
	if err != nil {
		return err
	}
	directory := filepath.Join(host.home, "Library", "LaunchAgents")
	link := filepath.Join(directory, label+".plist")
	verifyHost := func() error {
		for _, path := range []string{host.home, filepath.Dir(directory), directory} {
			if err := ordinaryLaunchDirectory(path, false); err != nil {
				return err
			}
		}
		return verifyLaunchRegistration(link, sourceFile)
	}
	if err = verifyHost(); err != nil {
		return fmt.Errorf("service-upgrade: registered LaunchAgent required: %w", err)
	}
	if err = check.target(); err != nil {
		return err
	}
	if id == "" {
		if err = check.source(); err != nil {
			return err
		}
	}
	if err = recheck(); err != nil {
		return err
	}
	domain := "gui/" + strconv.Itoa(host.uid)
	// Observe which configuration launchd currently holds. Fresh switches must
	// see the source; recovery may see either side or nothing, never unknown.
	loaded, pid, loadedIs := false, int64(0), []byte(nil)
	if id == "" {
		loaded, pid, err = inspectLaunchAgent(host.control, host.uid, label, source, sourceFile)
		if err != nil {
			return err
		}
		loadedIs = source
	} else {
		loaded, pid, err = inspectLaunchAgent(host.control, host.uid, label, target, sourceFile)
		if err == nil {
			loadedIs = target
		} else {
			loaded, pid, err = inspectLaunchAgent(host.control, host.uid, label, source, sourceFile)
			if err != nil {
				return errors.New("service-upgrade: loaded configuration matches neither transaction side; not unloading an unknown job")
			}
			loadedIs = source
		}
	}
	if id != "" && loaded && pid > 0 {
		if bytes.Equal(loadedIs, target) {
			if err = st.CheckServiceSwitchPending(); err != nil {
				return err
			}
			if _, err = st.VerifyLaunchAgent(key, target); err != nil {
				return err
			}
			if err = ready(); err != nil {
				return err
			}
			_, err = fmt.Fprintln(out, "目标版本已运行且健康，复用已完成的升级。")
			return err
		}
		return errors.New("service-upgrade: recovery requires a stopped job; the recorded source is still running")
	}
	if id == "" && loaded && pid > 0 {
		if _, err = fmt.Fprintln(out, "正在停止保护并切换已校验候选；block 模式下受控操作将暂时被拒绝。"); err != nil {
			return err
		}
		if _, err = host.control("stop", label); err != nil {
			return errors.New("launch-agent: stop failed or timed out; inspect launch-agent-status, configuration preserved")
		}
		deadline := time.Now().Add(35 * time.Second)
		for {
			pid, err = readLoadedLaunchAgent(host.control, host.uid, source, sourceFile)
			if err != nil {
				return err
			}
			if pid == 0 {
				break
			}
			if !time.Now().Before(deadline) {
				return errors.New("launch-agent: stop not confirmed before timeout")
			}
			time.Sleep(100 * time.Millisecond)
		}
		if err = stoppedLaunchAgent(host.control, host.uid, source, sourceFile, !rollback); err != nil {
			return err
		}
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	err = func() (writeErr error) {
		defer func() { writeErr = errors.Join(writeErr, writer.Release()) }()
		if err := verifyHost(); err != nil {
			return err
		}
		if id == "" {
			if err := check.source(); err != nil {
				return err
			}
			if err := check.target(); err != nil {
				return err
			}
			var err error
			id, err = st.PrepareLaunchAgentSwitch(writer, key, source, target, check.bindings)
			if err != nil {
				return err
			}
			if _, err = fmt.Fprintf(out, "切换事务：%s\n", id); err != nil {
				return err
			}
		}
		return st.ApplyLaunchAgentSwitch(writer, key, id)
	}()
	if err != nil {
		return err
	}
	if err = recheck(); err != nil {
		return err
	}
	if _, err = st.VerifyLaunchAgent(key, target); err != nil {
		return err
	}
	if err = check.target(); err != nil {
		return err
	}
	// launchd caches the plist at bootstrap; the loaded job must be unloaded
	// before the same link is bootstrapped again with the switched content.
	if loaded {
		if err = verifyHost(); err != nil {
			return err
		}
		if _, err = host.control("bootout", domain+"/"+label); err != nil {
			return errors.New("launch-agent: unload failed or timed out; configuration preserved, inspect status before retrying")
		}
		loaded, _, err = inspectLaunchAgent(host.control, host.uid, label, target, sourceFile)
		if err != nil {
			return err
		}
		if loaded {
			return errors.New("launch-agent: task absence not confirmed after unload")
		}
	}
	if err = verifyHost(); err != nil {
		return err
	}
	if _, err = host.control("bootstrap", domain, link); err != nil {
		return errors.New("launch-agent: loading failed or timed out; inspect launch-agent-status before retrying, configuration preserved")
	}
	loaded, pid, err = inspectLaunchAgent(host.control, host.uid, label, target, sourceFile)
	if err != nil {
		return err
	}
	if !loaded {
		return errors.New("launch-agent: loaded task not confirmed after bootstrap")
	}
	if _, err = st.VerifyLaunchAgent(key, target); err != nil {
		return err
	}
	if err = check.target(); err != nil {
		return err
	}
	if pid == 0 {
		if _, err = host.control("kickstart", domain+"/"+label); err != nil {
			return errors.New("launch-agent: start failed or timed out; inspect launch-agent-status before retrying")
		}
	}
	deadline := time.Now().Add(12 * time.Second)
	for {
		if err = verifyHost(); err != nil {
			return err
		}
		runtime, err := readLoadedLaunchRuntime(host.control, host.uid, target, sourceFile)
		if err != nil {
			return err
		}
		if runtime.PID > 0 && ready() == nil {
			break
		}
		if runtime.PID == 0 && runtime.LastExit != nil && *runtime.LastExit != 0 {
			return errors.New("service-upgrade: target readiness not confirmed")
		}
		if time.Now().After(deadline) {
			return errors.New("service-upgrade: target readiness not confirmed")
		}
		time.Sleep(100 * time.Millisecond)
	}
	_, err = fmt.Fprintln(out, "已切换到校验通过的目标版本，本实例 API 健康检查通过。")
	return err
}

func rollbackLaunchAgent(st *state.Store, host launchAgentSwitchHost, original string, plist []byte, recoverID string, out io.Writer, recheck, ready func() error, check *serviceBinaryCheck) error {
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadLaunchAgentSwitch(key, original)
	if err != nil {
		return err
	}
	if string(plist) != plan.SourcePlist {
		return errors.New("service-rollback: candidate does not reproduce original source configuration")
	}
	expected := state.ServiceBinaryBindings{SourceSHA256: plan.BinaryBindings.TargetSHA256, TargetSHA256: plan.BinaryBindings.SourceSHA256}
	if check == nil || check.bindings != expected {
		return errors.New("service-rollback: historical binary identity mismatch")
	}
	if err = switchLaunchAgent(st, host, []byte(plan.TargetPlist), plist, recoverID, out, recheck, ready, true, check); err != nil {
		return fmt.Errorf("service-rollback: retain --transaction %s when recovering: %w", original, err)
	}
	return nil
}

func currentLaunchAgentHost() (launchAgentSwitchHost, error) {
	home, uid, err := currentLaunchSession()
	if err != nil {
		return launchAgentSwitchHost{}, err
	}
	return launchAgentSwitchHost{home: home, uid: uid, control: runUserLaunchctl}, nil
}
