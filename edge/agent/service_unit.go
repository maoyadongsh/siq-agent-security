package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// Rendering does not install, enable, reload, start, register, or elevate.
// The eventual installer must independently verify binaries and device state.
func renderUserService(binary, stateDir, connectorDir string) (string, error) {
	for _, value := range []string{binary, stateDir, connectorDir} {
		if !filepath.IsAbs(value) || filepath.Clean(value) != value || value == "/" || strings.ContainsAny(value, "\"\\%$\n\r\t") {
			return "", errors.New("service paths must be canonical absolute paths without expansion characters")
		}
		for _, r := range value {
			if r < 32 || r == 127 {
				return "", errors.New("invalid service path")
			}
		}
	}
	return fmt.Sprintf(`[Unit]
Description=SIQ Agent Security enterprise discovery agent
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart="%s" serve
Environment="SIQ_EDGE_STATE_DIR=%s"
Environment="SIQ_CONNECTOR_BIN_DIR=%s"
UMask=0077
NoNewPrivileges=yes
Restart=on-failure
RestartSec=15
KillMode=control-group
TimeoutStopSec=90
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
`, binary, stateDir, connectorDir), nil
}

func writeServiceUnit(args []string, output io.Writer) error {
	fs := flag.NewFlagSet("service-unit", flag.ContinueOnError)
	binary := fs.String("binary", "", "verified absolute Edge executable path")
	state := fs.String("state-dir", "", "existing private registered device state directory")
	connectors := fs.String("connector-dir", "", "verified Connector installation directory")
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("service-unit accepts no positional arguments")
	}
	if runtime.GOOS != "linux" {
		return errors.New("service-unit currently requires Linux")
	}
	unit, err := renderUserService(*binary, *state, *connectors)
	if err != nil {
		return err
	}
	_, err = io.WriteString(output, unit)
	return err
}

func cmdServiceUnit(args []string) error { return writeServiceUnit(args, os.Stdout) }
