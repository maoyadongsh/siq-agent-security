package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"unicode"

	"siq-agent-security/apps/agentshield/internal/state"
)

func systemdQuote(value string) (string, error) {
	for _, r := range value {
		if unicode.IsControl(r) {
			return "", errors.New("service-unit: paths cannot contain control characters")
		}
	}
	return strconv.Quote(strings.ReplaceAll(value, "%", "%%")), nil
}

func renderUserUnit(binary, directory string) (string, error) {
	if !filepath.IsAbs(binary) || !filepath.IsAbs(directory) || strings.ContainsAny(binary, "$\"\\") {
		return "", errors.New("service-unit: absolute paths required; executable path cannot contain dollar signs, double quotes or backslashes")
	}
	command, err := systemdQuote(binary)
	if err != nil {
		return "", err
	}
	environment, err := systemdQuote("SIQ_AGENT_SECURITY_STATE_DIR=" + directory)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(`[Unit]
Description=SIQ Agent Security personal protection

[Service]
Type=exec
Environment=%s
ExecStart=%s serve
Restart=no
KillSignal=SIGTERM
TimeoutStopSec=30
UMask=0077
StandardOutput=null
StandardError=null

[Install]
WantedBy=default.target
`, environment, command), nil
}

func cmdServiceUnit(args []string, out io.Writer) error {
	if len(args) != 0 {
		return errors.New("service-unit: no arguments expected")
	}
	if runtime.GOOS != "linux" {
		return errors.New("service-unit: systemd export is only available on Linux")
	}
	dir, bin, err := currentServicePaths()
	if err != nil {
		return err
	}
	unit, err := renderUserUnit(bin, dir)
	if err != nil {
		return err
	}
	_, err = io.WriteString(out, unit)
	return err
}

// currentServicePaths is read-only and shared by platform service renderers.
func currentServicePaths() (string, string, error) {
	dir, err := state.DefaultDir()
	if err != nil {
		return "", "", err
	}
	dir, err = filepath.Abs(dir)
	if err == nil {
		dir, err = filepath.EvalSymlinks(dir)
	}
	if err != nil {
		return "", "", errors.New("service-unit: initialize the selected state directory first")
	}
	st := &state.Store{Dir: dir}
	if _, err := st.ReadLocalInstance(); err != nil {
		return "", "", errors.New("service-unit: valid initialized instance required")
	}
	// Initialize has already validated this file, but export must not accept a
	// deleted configuration as the loader's implicit defaults.
	info, err := os.Lstat(filepath.Join(dir, "config.json"))
	if err != nil || !info.Mode().IsRegular() || info.Size() > 65536 {
		return "", "", errors.New("service-unit: valid configuration required")
	}
	f, err := os.Open(filepath.Join(dir, "config.json"))
	if err != nil {
		return "", "", errors.New("service-unit: configuration unavailable")
	}
	raw, readErr := io.ReadAll(io.LimitReader(f, 65537))
	_ = f.Close()
	var object map[string]json.RawMessage
	if readErr != nil || len(raw) > 65536 || json.Unmarshal(raw, &object) != nil || object == nil {
		return "", "", errors.New("service-unit: invalid configuration")
	}
	if _, err := st.LoadConfig(); err != nil {
		return "", "", errors.New("service-unit: invalid configuration")
	}
	bin, err := os.Executable()
	if err == nil {
		bin, err = filepath.EvalSymlinks(bin)
	}
	if err != nil {
		return "", "", errors.New("service-unit: current executable unavailable")
	}

	return dir, bin, nil
}
