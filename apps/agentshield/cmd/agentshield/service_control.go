package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func ownedService(st *state.Store, unit []byte, control userSystemctl) (state.UserServiceRecord, map[string]string, error) {
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return state.UserServiceRecord{}, nil, err
	}
	record, err := st.VerifyUserService(key, unit)
	if err != nil {
		return record, nil, err
	}
	props, err := readUserUnit(control, record.UnitName)
	if err != nil {
		return record, nil, err
	}
	err = verifyUserUnit(props, filepath.Join(st.Dir, record.UnitName), props["UnitFileState"] == "linked-runtime")
	return record, props, err
}

func serviceRunning(props map[string]string) bool {
	pid, err := strconv.Atoi(props["MainPID"])
	return props["ActiveState"] == "active" && err == nil && pid > 0
}

func serviceStopped(st *state.Store, props map[string]string) error {
	if props["ActiveState"] != "inactive" || props["MainPID"] != "0" || props["Result"] != "success" {
		return errors.New("service: normal stop not confirmed; inspect the user manager")
	}
	if _, err := os.Lstat(filepath.Join(st.Dir, state.LockFile)); !errors.Is(err, os.ErrNotExist) {
		return errors.New("service: state writer still present or unreadable; stop incomplete")
	}
	return nil
}

func cmdServiceControl(action string, args []string, out io.Writer) (resultErr error) {
	if action == "stop" {
		if len(args) != 1 || args[0] != "--confirm-stop" {
			return errors.New("停止保护后，block 模式下智能体的后续受控操作会被拒绝；确认请运行 service-stop --confirm-stop")
		}
	} else if len(args) != 0 {
		return errors.New("service: no arguments expected")
	}
	var unit bytes.Buffer
	if err := cmdServiceUnit(nil, &unit); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	st := &state.Store{Dir: dir}
	// Status is read-only; mutations serialize independently of the daemon writer.
	if action != "status" {
		lock, err := state.AcquireWriter(filepath.Join(dir, "service-control"))
		if err != nil {
			return err
		}
		defer func() { resultErr = errors.Join(resultErr, lock.Release()) }()
	}
	record, props, err := ownedService(st, unit.Bytes(), runUserSystemctl)
	if err != nil {
		return err
	}
	if action == "stop" {
		if _, err = runUserSystemctl("stop", "--", record.UnitName); err != nil {
			return err
		}
		_, props, err = ownedService(st, unit.Bytes(), runUserSystemctl)
		if err != nil {
			return err
		}
		if err = serviceStopped(st, props); err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, "服务已正常停止；block 模式下后续受控操作将被拒绝。")
		return err
	}
	cfg, err := st.LoadConfig()
	if err != nil {
		return err
	}
	endpoint := fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	if action == "start" {
		if _, err = runUserSystemctl("start", "--", record.UnitName); err != nil {
			return err
		}
		deadline := time.Now().Add(12 * time.Second)
		for {
			_, props, err = ownedService(st, unit.Bytes(), runUserSystemctl)
			if err != nil {
				return err
			}
			if serviceRunning(props) {
				if _, err = probeLocalInstance(localClient(), endpoint, st); err == nil {
					break
				}
			}
			if props["ActiveState"] == "failed" || time.Now().After(deadline) {
				return errors.New("service: startup readiness not confirmed; inspect service-status")
			}
			time.Sleep(100 * time.Millisecond)
		}
	} else if action != "status" {
		return errors.New("service: unknown action")
	}
	if serviceRunning(props) {
		if _, err = probeLocalInstance(localClient(), endpoint, st); err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, "用户服务已运行，本地决策 API 就绪。")
		return err
	}
	if err = serviceStopped(st, props); err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "用户服务已注册，当前已停止；可运行 service-start。")
	return err
}
