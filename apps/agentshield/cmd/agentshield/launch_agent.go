package main

import (
	"bytes"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"path"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/state"
	"unicode"
	"unicode/utf8"
)

func renderLaunchAgent(binary, directory, instanceID string) (string, error) {
	raw, err := hex.DecodeString(instanceID)
	if err != nil || len(raw) != 32 || hex.EncodeToString(raw) != instanceID {
		return "", errors.New("launch-agent: invalid instance identity")
	}
	for _, value := range []string{binary, directory} {
		if !path.IsAbs(value) || path.Clean(value) != value || !utf8.ValidString(value) {
			return "", errors.New("launch-agent: canonical absolute UTF-8 paths required")
		}
		for _, r := range value {
			if unicode.IsControl(r) || r == 0xfffe || r == 0xffff {
				return "", errors.New("launch-agent: control characters in path")
			}
		}
	}
	escape := func(value string) (string, error) {
		var out bytes.Buffer
		err := xml.EscapeText(&out, []byte(value))
		return out.String(), err
	}
	executable, err := escape(binary)
	if err != nil {
		return "", err
	}
	stateDir, err := escape(directory)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.siq.agent-security.%s</string>
  <key>ProgramArguments</key><array><string>%s</string><string>serve</string></array>
  <key>EnvironmentVariables</key><dict><key>SIQ_AGENT_SECURITY_STATE_DIR</key><string>%s</string></dict>
  <key>RunAtLoad</key><false/>
  <key>KeepAlive</key><false/>
  <key>Umask</key><integer>63</integer>
  <key>ExitTimeOut</key><integer>30</integer>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict>
</plist>
`, instanceID, executable, stateDir), nil
}
func cmdLaunchAgentPlist(args []string, out io.Writer) error {
	if len(args) != 0 {
		return errors.New("launch-agent-plist: no arguments expected")
	}
	if runtime.GOOS != "darwin" {
		return errors.New("launch-agent-plist: macOS configuration export required")
	}
	dir, binary, err := currentServicePaths()
	if err != nil {
		return err
	}
	instance, err := (&state.Store{Dir: dir}).ReadLocalInstance()
	if err != nil {
		return err
	}
	plist, err := renderLaunchAgent(binary, dir, instance.InstanceID)
	if err != nil {
		return err
	}
	_, err = io.WriteString(out, plist)
	return err
}
