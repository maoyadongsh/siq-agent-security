package main

import (
	"errors"
	"os"
	"strings"
	"testing"
)

func TestLoadedLaunchAgentRequiresDomainAndFullConfiguration(t *testing.T) {
	expected, err := os.ReadFile("../../testdata/contracts/launch-agent.sample.plist")
	if err != nil {
		t.Fatal(err)
	}
	add := func(xml, fields string) string {
		at := strings.LastIndex(xml, "</dict>")
		return xml[:at] + fields + xml[at:]
	}
	for _, tc := range []struct {
		name, uid, manager, actual string
		pid                        int64
		valid                      bool
	}{
		{"loaded", "501", "Aqua", string(expected), 0, true},
		{"running", "501", "Aqua", add(string(expected), "<key>PID</key><integer>123</integer>"), 123, true},
		{"wrong user", "502", "Aqua", string(expected), 0, false},
		{"wrong session", "501", "Background", string(expected), 0, false},
		{"wrong argv", "501", "Aqua", strings.Replace(string(expected), "<string>serve</string>", "<string>other</string>", 1), 0, false},
		{"wrong environment", "501", "Aqua", strings.Replace(string(expected), "SIQ_AGENT_SECURITY_STATE_DIR", "OTHER", 1), 0, false},
		{"override", "501", "Aqua", add(string(expected), "<key>Program</key><string>/other</string>"), 0, false},
		{"PID zero", "501", "Aqua", add(string(expected), "<key>PID</key><integer>0</integer>"), 0, false},
		{"PID string", "501", "Aqua", add(string(expected), "<key>PID</key><string>123</string>"), 0, false},
		{"non XML", "501", "Aqua", "human diagnostic text", 0, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			listCalls := 0
			control := func(args ...string) (string, error) {
				switch args[0] {
				case "manageruid":
					return tc.uid + "\n", nil
				case "managername":
					return tc.manager + "\n", nil
				case "list":
					listCalls++
					if len(args) != 3 || args[1] != "-x" || args[2] != "dev.siq.agent-security."+strings.Repeat("a", 64) {
						t.Fatal("unsafe list query", args)
					}
					return tc.actual, nil
				default:
					t.Fatal("mutation attempted", args)
					return "", nil
				}
			}
			pid, err := readLoadedLaunchAgent(control, 501, expected)
			if (err == nil) != tc.valid || (tc.valid && pid != tc.pid) {
				t.Fatal("unexpected verification", pid, err)
			}
			if (tc.uid != "501" || tc.manager != "Aqua") && listCalls != 0 {
				t.Fatal("queried foreign domain")
			}
		})
	}
	if _, err := readLoadedLaunchAgent(func(...string) (string, error) { t.Fatal("root queried manager"); return "", nil }, 0, expected); err == nil {
		t.Fatal("root accepted")
	}
	if _, err := readLoadedLaunchAgent(func(...string) (string, error) { return "", errors.New("unavailable") }, 501, expected); err == nil {
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
