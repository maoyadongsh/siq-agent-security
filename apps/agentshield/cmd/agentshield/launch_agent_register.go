package main

import (
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
)

func launchAgentLabelValid(label string) bool {
	const prefix = "dev.siq.agent-security."
	if !strings.HasPrefix(label, prefix) {
		return false
	}
	value := strings.TrimPrefix(label, prefix)
	raw, err := hex.DecodeString(value)
	return err == nil && len(raw) == 32 && hex.EncodeToString(raw) == value
}
func syncLaunchAgentDirectory(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}
func ordinaryLaunchDirectory(path string, create bool) error {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return errors.New("launch-agent: absolute canonical directory required")
	}
	if create {
		if err := os.Mkdir(path, 0700); err != nil && !errors.Is(err, os.ErrExist) {
			return err
		}
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("launch-agent: ordinary directory required")
	}
	canonical, err := filepath.EvalSymlinks(path)
	if err != nil || canonical != path {
		return errors.New("launch-agent: canonical directory required")
	}
	return nil
}
func verifyLaunchRegistration(link, source string) error {
	info, err := os.Lstat(link)
	if err != nil {
		return err
	}
	if info.Mode()&os.ModeSymlink == 0 {
		return errors.New("launch-agent: unowned registration file")
	}
	target, err := os.Readlink(link)
	if err != nil {
		return err
	}
	if target != source {
		return errors.New("launch-agent: registration belongs to another source")
	}
	info, err = os.Lstat(source)
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() || info.Size() > 16384 || info.Size() == 0 {
		return errors.New("launch-agent: invalid source configuration")
	}
	return nil
}

// The caller verifies the signed source before and after publication while
// retaining the lifecycle and main writer locks.
func publishLaunchRegistration(home, source, label string) (string, error) {
	if !launchAgentLabelValid(label) || !filepath.IsAbs(source) || filepath.Clean(source) != source || filepath.Base(source) != label+".plist" {
		return "", errors.New("launch-agent: invalid registration identity")
	}
	if err := ordinaryLaunchDirectory(home, false); err != nil {
		return "", err
	}
	info, err := os.Lstat(source)
	if err != nil {
		return "", err
	}
	if !info.Mode().IsRegular() || info.Size() < 1 || info.Size() > 16384 {
		return "", errors.New("launch-agent: invalid source configuration")
	}
	library := filepath.Join(home, "Library")
	directory := filepath.Join(library, "LaunchAgents")
	for _, path := range []string{library, directory} {
		if err := ordinaryLaunchDirectory(path, true); err != nil {
			return "", err
		}
		if err := syncLaunchAgentDirectory(filepath.Dir(path)); err != nil {
			return "", err
		}
	}
	link := filepath.Join(directory, label+".plist")
	if err := os.Symlink(source, link); err != nil && !errors.Is(err, os.ErrExist) {
		return "", err
	}
	if err := verifyLaunchRegistration(link, source); err != nil {
		return "", err
	}
	if err := syncLaunchAgentDirectory(directory); err != nil {
		return "", err
	}
	return link, nil
}
func cmdLaunchAgentRegister(args []string, out io.Writer) error {
	return withPreparedLaunchAgent(args, func(st *state.Store, key *signing.Key, plist []byte, record state.LaunchAgentRecord) error {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		home, err = filepath.EvalSymlinks(home)
		if err != nil {
			return err
		}
		source, err := filepath.Abs(filepath.Join(st.Dir, record.Label+".plist"))
		if err != nil {
			return err
		}
		source, err = filepath.EvalSymlinks(source)
		if err != nil {
			return err
		}
		if _, err = st.VerifyLaunchAgent(key, plist); err != nil {
			return err
		}
		link, err := publishLaunchRegistration(home, source, record.Label)
		if err != nil {
			return err
		}
		if _, err = st.VerifyLaunchAgent(key, plist); err != nil {
			return err
		}
		if err = verifyLaunchRegistration(link, source); err != nil {
			return err
		}
		_, err = fmt.Fprintf(out, "已发布当前用户 LaunchAgent 配置：%s\n尚未确认加载或启动，保护未因此启用。\n", link)
		return err
	})
}
