package main

import (
	"bytes"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func runtimeUserUnit(props map[string]string) bool {
	return props["UnitFileState"] == "linked-runtime" || props["UnitFileState"] == "enabled-runtime"
}
func loginLinkPath(fragment string) string {
	return filepath.Join(filepath.Dir(fragment), "default.target.wants", filepath.Base(fragment))
}
func verifyLoginLink(fragment, target string) error {
	path := loginLinkPath(fragment)
	parent, err := os.Lstat(filepath.Dir(path))
	if err != nil {
		return err
	}
	if !parent.IsDir() || parent.Mode()&os.ModeSymlink != 0 {
		return errors.New("service-login: unsafe wants directory")
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink == 0 {
		return errors.New("service-login: startup entry is not an owned symlink")
	}
	actual, err := filepath.EvalSymlinks(path)
	if err != nil {
		return err
	}
	expected, err := filepath.EvalSymlinks(target)
	if err != nil {
		return err
	}
	if actual != expected {
		return errors.New("service-login: startup entry belongs to another source")
	}
	return nil
}
func setUserLogin(control userSystemctl, path, name string, enable bool) error {
	props, err := readUserUnit(control, name)
	if err != nil {
		return err
	}
	runtimeOnly := runtimeUserUnit(props)
	if err = verifyUserUnit(props, path, runtimeOnly); err != nil {
		// An interrupted disable may already have removed the exact link;
		// only reload recovery is permitted, without adopting another entry.
		if enable || (props["UnitFileState"] != "enabled" && props["UnitFileState"] != "enabled-runtime") {
			return err
		}
		if _, missing := os.Lstat(loginLinkPath(props["FragmentPath"])); !errors.Is(missing, os.ErrNotExist) {
			return err
		}
		copyProps := make(map[string]string, len(props))
		for k, v := range props {
			copyProps[k] = v
		}
		copyProps["UnitFileState"] = "linked"
		if runtimeOnly {
			copyProps["UnitFileState"] = "linked-runtime"
		}
		if verifyErr := verifyUserUnit(copyProps, path, runtimeOnly); verifyErr != nil {
			return verifyErr
		}
	}
	fragment := props["FragmentPath"]
	info, err := os.Lstat(fragment)
	if err != nil {
		return err
	}
	if !filepath.IsAbs(fragment) || filepath.Base(fragment) != name || info.Mode()&os.ModeSymlink == 0 {
		return errors.New("service-login: owned registration symlink required")
	}
	parent := filepath.Dir(fragment)
	canonical, err := filepath.EvalSymlinks(parent)
	if err != nil || canonical != parent {
		return errors.New("service-login: canonical registration directory required")
	}
	link := loginLinkPath(fragment)
	wants := filepath.Dir(link)
	if enable {
		if err = os.Mkdir(wants, 0700); err != nil && !errors.Is(err, os.ErrExist) {
			return err
		}
	}
	if info, err := os.Lstat(wants); err == nil {
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return errors.New("service-login: unsafe wants directory")
		}
	} else if !errors.Is(err, os.ErrNotExist) || enable {
		return err
	}
	_, statErr := os.Lstat(link)
	if statErr == nil {
		if err = verifyLoginLink(fragment, path); err != nil {
			return err
		}
		if !enable {
			if err = os.Remove(link); err != nil {
				return err
			}
		}
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return statErr
	} else if enable {
		if err = os.Symlink(path, link); err != nil {
			return err
		}
	}
	if d, err := os.Open(wants); err == nil {
		syncErr := d.Sync()
		d.Close()
		if syncErr != nil {
			return syncErr
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	parentDir, err := os.Open(parent)
	if err != nil {
		return err
	}
	syncErr := parentDir.Sync()
	parentDir.Close()
	if syncErr != nil {
		return syncErr
	}
	if _, err = control("daemon-reload"); err != nil {
		return err
	}
	props, err = readUserUnit(control, name)
	if err != nil {
		return err
	}
	if err = verifyUserUnit(props, path, runtimeOnly); err != nil {
		return err
	}
	expected := "linked"
	if enable {
		expected = "enabled"
	}
	if runtimeOnly {
		expected += "-runtime"
	}
	if props["UnitFileState"] != expected {
		return errors.New("service-login: manager did not confirm requested startup state")
	}
	if enable {
		return verifyLoginLink(fragment, path)
	}
	if _, err = os.Lstat(link); !errors.Is(err, os.ErrNotExist) {
		return errors.New("service-login: startup entry remains")
	}
	return nil
}
func cmdServiceLogin(args []string, out io.Writer) (resultErr error) {
	fs := flag.NewFlagSet("service-login", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	enable := fs.Bool("enable", false, "enable login startup")
	disable := fs.Bool("disable", false, "disable login startup")
	confirm := fs.Bool("confirm-enable", false, "confirm future login startup")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *enable == *disable || (*enable && !*confirm) || (*disable && *confirm) || fs.NArg() != 0 {
		return errors.New("service-login: use --enable --confirm-enable or --disable")
	}
	var unit bytes.Buffer
	if err := cmdServiceUnit(nil, &unit); err != nil {
		return err
	}
	dir, err := state.DefaultDir()
	if err != nil {
		return err
	}
	lock, err := state.AcquireWriter(filepath.Join(dir, "service-control"))
	if err != nil {
		return err
	}
	defer func() { resultErr = errors.Join(resultErr, lock.Release()) }()
	st := &state.Store{Dir: dir}
	key, err := signing.LoadExisting(dir)
	if err != nil {
		return err
	}
	record, err := st.VerifyUserService(key, unit.Bytes())
	if err != nil {
		return err
	}
	path, err := filepath.Abs(filepath.Join(dir, record.UnitName))
	if err != nil {
		return err
	}
	if err = setUserLogin(runUserSystemctl, path, record.UnitName, *enable); err != nil {
		return err
	}
	_, err = fmt.Fprintln(out, "用户服务启动入口已更新，当前运行进程未重启或停止。runtime 注册仅本登录会话有效；持久注册的启用项在后续登录生效。")
	return err
}
