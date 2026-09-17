package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadedLaunchAgentRequiresDomainAndFullConfiguration(t *testing.T) {
	expected, err := os.ReadFile("../../testdata/contracts/launch-agent.sample.plist")
	if err != nil {
		t.Fatal(err)
	}
	wanted, err := decodeLaunchPlist(string(expected))
	if err != nil {
		t.Fatal(err)
	}
	label, _ := wanted["Label"].(string)
	source := filepath.Join(t.TempDir(), label+".plist")
	if err := os.WriteFile(source, expected, 0600); err != nil {
		t.Fatal(err)
	}
	loaded := mustLaunchPrint(t, string(expected), source, 0, "", "")
	running := mustLaunchPrint(t, string(expected), source, 123, "", "")
	wrongArgv := mustLaunchPrint(t, string(expected), source, 0, "", "other")
	wrongEnv := strings.Replace(loaded, "SIQ_AGENT_SECURITY_STATE_DIR", "OTHER", 1)
	wrongPath := strings.Replace(loaded, mustResolve(t, source), "/other/source.plist", 1)
	pidZero := strings.Replace(running, "pid = 123", "pid = 0", 1)
	pidString := strings.Replace(running, "pid = 123", "pid = abc", 1)
	for _, tc := range []struct {
		name, uid, manager, actual string
		pid                        int64
		valid                      bool
	}{
		{"loaded", "501", "Aqua", loaded, 0, true},
		{"running", "501", "Aqua", running, 123, true},
		{"wrong user", "502", "Aqua", loaded, 0, false},
		{"wrong session", "501", "Background", loaded, 0, false},
		{"wrong argv", "501", "Aqua", wrongArgv, 0, false},
		{"wrong environment", "501", "Aqua", wrongEnv, 0, false},
		{"wrong path", "501", "Aqua", wrongPath, 0, false},
		{"PID zero", "501", "Aqua", pidZero, 0, false},
		{"PID string", "501", "Aqua", pidString, 0, false},
		{"non print", "501", "Aqua", "human diagnostic text\n", 0, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			listCalls := 0
			control := func(args ...string) (string, error) {
				switch args[0] {
				case "manageruid":
					return tc.uid + "\n", nil
				case "managername":
					return tc.manager + "\n", nil
				case "print":
					listCalls++
					if len(args) != 2 || args[1] != launchPrintTarget(501, label) {
						t.Fatal("unsafe print query", args)
					}
					return tc.actual, nil
				default:
					t.Fatal("mutation attempted", args)
					return "", nil
				}
			}
			pid, err := readLoadedLaunchAgent(control, 501, expected, source)
			if (err == nil) != tc.valid || (tc.valid && pid != tc.pid) {
				t.Fatal("unexpected verification", pid, err)
			}
			if (tc.uid != "501" || tc.manager != "Aqua") && listCalls != 0 {
				t.Fatal("queried foreign domain")
			}
		})
	}
	if _, err := readLoadedLaunchAgent(func(...string) (string, error) { t.Fatal("root queried manager"); return "", nil }, 0, expected, source); err == nil {
		t.Fatal("root accepted")
	}
	if _, err := readLoadedLaunchAgent(func(...string) (string, error) { return "", errors.New("unavailable") }, 501, expected, source); err == nil {
		t.Fatal("query error interpreted as absence")
	}
}
func TestLaunchPlistReaderRejectsAmbiguityAndBudgets(t *testing.T) {
	wrap := func(body string) string { return `<plist version="1.0"><dict>` + body + `</dict></plist>` }
	for _, raw := range []string{
		wrap(`<key>a</key><string>x</string><key>a</key><string>y</string>`),
		wrap(`<key>a</key><string><dict/></string>`),
		wrap(`<key>a</key><true>unexpected</true>`),
		wrap(`<key>a</key><string xmlns="other">x</string>`),
		wrap(`<key>a</key><integer>1.2</integer>`),
		wrap(`<key>a</key>`),
		wrap(`<key>a</key>` + strings.Repeat(`<array>`, 18) + strings.Repeat(`</array>`, 18)),
		wrap(`<key>a</key><array>` + strings.Repeat(`<true/>`, 2048) + `</array>`),
		wrap("") + wrap(""), strings.Repeat("x", 65537),
	} {
		if _, err := decodeLaunchPlist(raw); err == nil {
			t.Fatal("invalid plist accepted")
		}
	}
}
