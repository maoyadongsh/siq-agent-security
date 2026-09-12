package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func cmdTeardown(args []string, out io.Writer) error {
	if len(args) != 1 || args[0] != "--confirm-teardown" {
		return errors.New("停止后台服务后 block 模式受控操作将拒绝；请使用 teardown --confirm-teardown，配置与历史数据将保留")
	}
	var unit bytes.Buffer
	if err := cmdServiceUnit(nil, &unit); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	if err := teardownUserService(&state.Store{Dir: dir}, unit.Bytes(), runUserSystemctl); err != nil {
		return fmt.Errorf("teardown: 未完成，已完成步骤保留，可检查后重试: %w", err)
	}
	_, err = fmt.Fprintln(out, "当前实例后台入口已移除，服务已停止。程序、配置、身份与历史数据已保留；智能体钩子未卸载，block 模式受控操作将拒绝。")
	return err
}
func teardownUserService(st *state.Store, unit []byte, control userSystemctl) (resultErr error) {
	lock, err := state.AcquireWriter(filepath.Join(st.Dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lock.Release()) }()
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		return err
	}
	record, err := st.VerifyUserService(key, unit)
	if err != nil {
		return err
	}
	if err = st.CheckServiceSwitchPending(); err != nil {
		return err
	}
	path, err := filepath.Abs(filepath.Join(st.Dir, record.UnitName))
	if err != nil {
		return err
	}
	props, err := readUserUnit(control, record.UnitName)
	if err != nil {
		return err
	}
	if !unitAbsent(props) {
		// Only the existing unregister recovery handles a previously removed link.
		_, fragmentErr := os.Lstat(props["FragmentPath"])
		_, loginErr := os.Lstat(loginLinkPath(props["FragmentPath"]))
		removedRegistration := errors.Is(fragmentErr, os.ErrNotExist) && errors.Is(loginErr, os.ErrNotExist)
		if removedRegistration {
			if err = serviceStopped(st, props); err != nil {
				return err
			}
		} else {
			if err = setUserLogin(control, path, record.UnitName, false); err != nil {
				return err
			}
			if _, _, err = ownedService(st, unit, control); err != nil {
				return err
			}
			if _, err = control("stop", "--", record.UnitName); err != nil {
				return err
			}
			_, props, err = ownedService(st, unit, control)
			if err != nil {
				return err
			}
			if err = serviceStopped(st, props); err != nil {
				return err
			}
		}
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, writer.Release()) }()
	if _, err = st.VerifyUserService(key, unit); err != nil {
		return err
	}
	return unregisterUserUnit(control, path, record.UnitName)
}
