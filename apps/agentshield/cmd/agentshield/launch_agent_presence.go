package main

import (
	"errors"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Presence is a point-in-time observation, never ownership or permission to replace.
func inspectLaunchAgent(control userSystemctl, uid int, label string, expected []byte) (bool, int64, error) {
	if !launchAgentLabelValid(label) {
		return false, 0, errors.New("launch-agent: invalid expected label")
	}
	wanted, err := decodeLaunchPlist(string(expected))
	if err != nil || wanted["Label"] != label {
		return false, 0, errors.New("launch-agent: expected configuration label mismatch")
	}
	if err := verifyLaunchUserDomain(control, uid); err != nil {
		return false, 0, err
	}
	raw, err := control("list")
	if err != nil {
		return false, 0, errors.New("launch-agent: task enumeration failed; state is unconfirmed")
	}
	present, err := launchListContains(raw, label)
	if err != nil || !present {
		return false, 0, err
	}
	// A disappeared or changed job must not become an absence result here.
	pid, err := readLoadedLaunchAgent(control, uid, expected)
	if err != nil {
		return false, 0, err
	}
	return true, pid, nil
}

func launchListContains(raw, label string) (bool, error) {
	invalid := errors.New("launch-agent: invalid or unsupported task enumeration; state is unconfirmed")
	if len(raw) > 65536 || !utf8.ValidString(raw) || !strings.HasSuffix(raw, "\n") {
		return false, invalid
	}
	lines := strings.Split(strings.TrimSuffix(raw, "\n"), "\n")
	if lines[0] != "PID\tStatus\tLabel" {
		return false, invalid
	}
	seen := make(map[string]bool)
	for _, line := range lines[1:] {
		fields := strings.Split(line, "\t")
		if len(fields) != 3 || fields[2] == "" || strings.IndexFunc(fields[2], unicode.IsControl) >= 0 || seen[fields[2]] {
			return false, invalid
		}
		if fields[0] != "-" {
			pid, err := strconv.ParseInt(fields[0], 10, 64)
			if err != nil || pid <= 0 || strconv.FormatInt(pid, 10) != fields[0] {
				return false, invalid
			}
		}
		if fields[1] != "-" && fields[1] != "???" {
			status, err := strconv.ParseInt(fields[1], 10, 64)
			if err != nil || strconv.FormatInt(status, 10) != fields[1] {
				return false, invalid
			}
		}
		seen[fields[2]] = true
	}
	return seen[label], nil
}
