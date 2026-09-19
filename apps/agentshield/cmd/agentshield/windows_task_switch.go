package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os/user"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type windowsTaskSwitchHost struct {
	sid      string
	presence func(string, string) (bool, error)
	query    func(string) ([]byte, error)
	runtime  func(string, string) (string, error)
	remove   func(string, string, []byte) error
	create   func(string, string, []byte) error
	start    func(string, string) error
	stop     func(*state.Store, *signing.Key, []byte) error
	wait     time.Duration
}

type windowsSwitchObservation struct {
	side     string // absent, source, target
	runtime  windowsTaskRuntime
	snapshot []byte
}

// inspect authenticates the complete system configuration on both sides of the
// runtime query. Local files may be a partial pair during explicit recovery.
func (h windowsTaskSwitchHost) inspect(name string, source, target []byte) (windowsSwitchObservation, error) {
	var result windowsSwitchObservation
	present, err := h.presence(name, h.sid)
	if err != nil {
		return result, errors.New("task-switch: task presence unconfirmed")
	}
	if !present {
		result.side = "absent"
		return result, nil
	}
	read := func() ([]byte, error) {
		raw, err := h.query(name)
		if err != nil {
			return nil, errors.New("task-switch: task query unconfirmed")
		}
		return decodeWindowsTaskOutput(raw)
	}
	xml, err := read()
	if err != nil {
		return result, err
	}
	want := source
	switch {
	case verifyWindowsTaskXML(xml, source) == nil:
		result.side = "source"
	case verifyWindowsTaskXML(xml, target) == nil:
		result.side, want = "target", target
	default:
		return result, errors.New("task-switch: unknown task configuration; not removing it")
	}
	raw, err := h.runtime(name, h.sid)
	if err != nil {
		return result, errors.New("task-switch: runtime unconfirmed")
	}
	result.runtime, err = decodeWindowsTaskRuntime(raw)
	if err != nil {
		return result, err
	}
	result.snapshot, err = read()
	if err != nil {
		return result, err
	}
	if err = verifyWindowsTaskXML(result.snapshot, want); err != nil {
		return result, err
	}
	return result, nil
}

func switchWindowsTask(st *state.Store, host windowsTaskSwitchHost, source, target []byte, recoverID string, out io.Writer, recheck, ready func() error, check *serviceBinaryCheck) (resultErr error) {
	if check == nil || !state.WindowsUserSIDValid(host.sid) {
		return errors.New("task-switch: binary bindings and current user required")
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
			resultErr = fmt.Errorf("task-switch: transaction %s incomplete; retain candidate and retry with --recover %s: %w", id, id, resultErr)
		}
	}()
	var record state.WindowsTaskRecord
	if id == "" {
		if err = st.CheckServiceSwitchPending(); err != nil {
			return err
		}
		record, err = st.VerifyWindowsTask(key, source, host.sid)
		if err != nil {
			return err
		}
		if err = check.source(); err != nil {
			return err
		}
	} else {
		plan, err := st.ReadWindowsTaskSwitch(key, id)
		if err != nil {
			return err
		}
		if plan.SourceXML != string(source) || plan.TargetXML != string(target) || plan.BinaryBindings != check.bindings || plan.SourceRecord.UserSID != host.sid {
			return errors.New("task-switch: recovery candidate or user differs from journal")
		}
		if err = st.CheckWindowsTaskSwitchRecovery(key, id); err != nil {
			return err
		}
		record = plan.SourceRecord
	}
	if bytes.Equal(source, target) {
		return errors.New("task-switch: target has no configuration change")
	}
	if err = check.target(); err != nil {
		return err
	}
	if err = recheck(); err != nil {
		return err
	}
	current, err := host.inspect(record.TaskName, source, target)
	if err != nil {
		return err
	}
	if id == "" {
		if current.side != "source" {
			return errors.New("task-switch: registered source task required")
		}
		if current.runtime.State == "queued" {
			return errors.New("task-switch: queued source cannot be switched")
		}
		if _, err = fmt.Fprintln(out, "正在停止本实例保护并切换已校验候选；block 模式将暂时拒绝受控操作。"); err != nil {
			return err
		}
		if err = host.stop(st, key, source); err != nil {
			return err
		}
	} else if current.side != "absent" && current.runtime.State != "ready" {
		if current.side != "target" || current.runtime.State != "running" {
			return errors.New("task-switch: recovery requires an idle source or completed running target")
		}
		if err = st.CheckWindowsTaskSwitchCompleted(key, id); err != nil {
			return err
		}
		if err = ready(); err != nil {
			return err
		}
		if err = verifyRunningWindowsSwitch(st, key, host, record.TaskName, source, target, check); err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, "目标任务已运行且版本健康，复用已完成的切换。")
		return err
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	err = func() (writeErr error) {
		defer func() { writeErr = errors.Join(writeErr, writer.Release()) }()
		if err := recheck(); err != nil {
			return err
		}
		if err := check.target(); err != nil {
			return err
		}
		current, err := host.inspect(record.TaskName, source, target)
		if err != nil {
			return err
		}
		if current.side != "absent" && current.runtime.State != "ready" {
			return errors.New("task-switch: task must remain idle")
		}
		if id == "" {
			if current.side != "source" {
				return errors.New("task-switch: source changed during stop")
			}
			if err := check.source(); err != nil {
				return err
			}
			id, err = st.PrepareWindowsTaskSwitch(writer, key, source, target, host.sid, check.bindings)
			if err != nil {
				return err
			}
			if _, err = fmt.Fprintf(out, "切换事务：%s\n", id); err != nil {
				return err
			}
		}
		if err = st.CheckWindowsTaskSwitchRecovery(key, id); err != nil {
			return err
		}
		if current.side == "source" {
			if err = host.remove(record.TaskName, host.sid, current.snapshot); err != nil {
				return errors.New("task-switch: source deletion unconfirmed; preserve transaction")
			}
			present, err := host.presence(record.TaskName, host.sid)
			if err != nil || present {
				return errors.New("task-switch: source absence unconfirmed")
			}
			current.side = "absent"
		}
		if err = st.ApplyWindowsTaskSwitch(writer, key, id); err != nil {
			return err
		}
		if err = check.target(); err != nil {
			return err
		}
		if err = recheck(); err != nil {
			return err
		}
		if current.side == "absent" {
			if err = host.create(record.TaskName, host.sid, target); err != nil {
				return errors.New("task-switch: exclusive target creation unconfirmed; preserve transaction")
			}
		}
		current, err = host.inspect(record.TaskName, source, target)
		if err != nil {
			return err
		}
		if current.side != "target" || current.runtime.State != "ready" {
			return errors.New("task-switch: idle target not confirmed")
		}
		if _, err = st.VerifyWindowsTask(key, target, host.sid); err != nil {
			return err
		}
		return st.FinishWindowsTaskSwitch(writer, key, id)
	}()
	if err != nil {
		return err
	}
	if err = recheck(); err != nil {
		return err
	}
	if err = check.target(); err != nil {
		return err
	}
	health := func() error {
		if err := verifyRunningWindowsSwitch(st, key, host, record.TaskName, source, target, check); err != nil {
			return err
		}
		return ready()
	}
	if err = startOwnedWindowsTask(st, key, target, host.sid, host.query, host.start, health, host.wait); err != nil {
		return err
	}
	if err = health(); err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "已切换到校验通过的目标版本，任务运行与本实例 API 版本健康检查通过。")
	return err
}

func verifyRunningWindowsSwitch(st *state.Store, key *signing.Key, host windowsTaskSwitchHost, name string, source, target []byte, check *serviceBinaryCheck) error {
	if _, err := st.VerifyWindowsTask(key, target, host.sid); err != nil {
		return err
	}
	if err := check.target(); err != nil {
		return err
	}
	current, err := host.inspect(name, source, target)
	if err != nil {
		return err
	}
	if current.side != "target" || current.runtime.State != "running" {
		return errors.New("task-switch: running target not confirmed")
	}
	return nil
}

func currentWindowsTaskSwitchHost() (windowsTaskSwitchHost, error) {
	current, err := user.Current()
	if err != nil || !state.WindowsUserSIDValid(current.Uid) {
		return windowsTaskSwitchHost{}, errors.New("task-switch: current Windows user unavailable")
	}
	h := windowsTaskSwitchHost{sid: current.Uid, presence: runWindowsTaskPresence, query: runWindowsTaskQuery, runtime: runWindowsTaskRuntime, remove: runWindowsTaskDelete, create: runWindowsTaskCreate, start: runWindowsTaskStart, wait: 12 * time.Second}
	h.stop = func(st *state.Store, key *signing.Key, source []byte) error {
		cfg, err := st.LoadConfig()
		if err != nil {
			return err
		}
		client := localClient()
		defer client.CloseIdleConnections()
		request := func() (state.ServiceStopAcceptance, error) {
			return requestSignedLocalStop(client, fmt.Sprintf("http://127.0.0.1:%d", cfg.Port), st, key)
		}
		return stopOwnedWindowsTask(st, key, source, h.sid, h.query, h.runtime, request, 35*time.Second)
	}
	return h, nil
}

func rollbackWindowsTask(st *state.Store, host windowsTaskSwitchHost, original string, target []byte, recoverID string, out io.Writer, recheck, ready func() error, check *serviceBinaryCheck) error {
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	plan, err := st.ReadWindowsTaskSwitch(key, original)
	if err != nil {
		return err
	}
	if string(target) != plan.SourceXML || check == nil || check.bindings != (state.ServiceBinaryBindings{SourceSHA256: plan.BinaryBindings.TargetSHA256, TargetSHA256: plan.BinaryBindings.SourceSHA256}) {
		return errors.New("service-rollback: candidate differs from original source")
	}
	// A new rollback requires a completed forward switch. Recovery instead
	// authenticates its own reverse journal and barrier inside switchWindowsTask.
	if recoverID == "" {
		if err = st.CheckWindowsTaskSwitchCompleted(key, original); err != nil {
			return err
		}
	}
	if err = switchWindowsTask(st, host, []byte(plan.TargetXML), target, recoverID, out, recheck, ready, check); err != nil {
		return fmt.Errorf("service-rollback: retain --transaction %s during recovery: %w", original, err)
	}
	return nil
}
