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

func unitAbsent(p map[string]string) bool {
	return p["LoadState"] == "not-found" && p["FragmentPath"] == "" && p["DropInPaths"] == "" && p["UnitFileState"] == "" && p["ActiveState"] == "inactive" && p["MainPID"] == "0"
}

// Remove exactly the loaded registration symlink, never all links to a unit.
func unregisterUserUnit(control userSystemctl, path, name string) error {
	p, err := readUserUnit(control, name)
	if err != nil {
		return err
	}
	if unitAbsent(p) {
		return nil
	}
	if p["ActiveState"] != "inactive" || p["MainPID"] != "0" || p["Result"] != "success" {
		return errors.New("service-unregister: stop the service normally before unregistering")
	}
	fragment := p["FragmentPath"]
	if p["LoadState"] != "loaded" || p["DropInPaths"] != "" || (p["UnitFileState"] != "linked" && p["UnitFileState"] != "linked-runtime") || !filepath.IsAbs(fragment) || filepath.Base(fragment) != name {
		return errors.New("service-unregister: unexpected unit or overrides; refusing removal")
	}
	info, err := os.Lstat(fragment)
	if err == nil {
		if info.Mode()&os.ModeSymlink == 0 {
			return errors.New("service-unregister: registration is not a symlink; refusing removal")
		}
		if err = verifyUserUnit(p, path, p["UnitFileState"] == "linked-runtime"); err != nil {
			return err
		}
		if err = os.Remove(fragment); err != nil {
			return err
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	// If the owned link was removed before an interrupted reload, no further
	// deletion is needed. Reload is read-back recovery, not a new adoption.
	if _, err = control("daemon-reload"); err != nil {
		return err
	}
	p, err = readUserUnit(control, name)
	if err != nil {
		return err
	}
	if !unitAbsent(p) {
		return errors.New("service-unregister: removal not confirmed; inspect the user manager before retrying")
	}
	return nil
}

func cmdServiceUnregister(args []string, out io.Writer) (resultErr error) {
	if len(args) != 1 || args[0] != "--confirm-unregister" {
		return errors.New("注销用户服务将移除后台入口并保留本地数据；请先停止服务，再执行 service-unregister --confirm-unregister")
	}
	var unit bytes.Buffer
	if err := cmdServiceUnit(nil, &unit); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	lifecycle, err := state.AcquireWriter(filepath.Join(dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lifecycle.Release()) }()
	w, err := state.AcquireWriter(dir)
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, w.Release()) }()
	st := &state.Store{Dir: dir}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		return err
	}
	record, err := st.VerifyUserService(key, unit.Bytes())
	if err != nil {
		return err
	}
	if err = unregisterUserUnit(runUserSystemctl, filepath.Join(dir, record.UnitName), record.UnitName); err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "当前实例已无服务注册；配置、密钥与历史记录已保留。")
	return err
}
