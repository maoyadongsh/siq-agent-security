package main

import (
	"errors"
	"os"
	"strings"
	"testing"
)

func TestLaunchListPresenceRequiresCompleteUnambiguousEnumeration(t *testing.T) {
	const header = "PID\tStatus\tLabel\n"
	for _, tc := range []struct {
		name, raw      string
		present, valid bool
	}{
		{"empty domain", header, false, true},
		{"other jobs", header + "-\t0\tother\n123\t-\trunning\n-\t-9\tkilled\n-\t???\tunknown status\n", false, true},
		{"idle target", header + "-\t-\ttarget\n", true, true},
		{"running target", header + "123\t0\ttarget\n", true, true},
		{"exact match", header + "-\t0\ttarget.extra\n", false, true},
		{"no output", "", false, false},
		{"no header", "-\t0\tother\n", false, false},
		{"truncated", header + "-\t0\tother", false, false},
		{"duplicate target", header + "-\t0\ttarget\n-\t0\ttarget\n", false, false},
		{"duplicate other", header + "-\t0\tother\n-\t0\tother\n", false, false},
		{"garbage after match", header + "-\t0\ttarget\nunexpected diagnostic\n", false, false},
		{"empty label", header + "-\t0\t\n", false, false},
		{"empty row", header + "\n", false, false},
		{"extra column", header + "-\t0\tother\textra\n", false, false},
		{"control label", header + "-\t0\tother\r\n", false, false},
		{"invalid utf8", header + "-\t0\t\xff\n", false, false},
		{"zero PID", header + "0\t0\tother\n", false, false},
		{"negative PID", header + "-1\t0\tother\n", false, false},
		{"PID overflow", header + "9223372036854775808\t0\tother\n", false, false},
		{"status overflow", header + "-\t9223372036854775808\tother\n", false, false},
		{"ambiguous status", header + "-\t+0\tother\n", false, false},
		{"text status", header + "-\terror\tother\n", false, false},
		{"budget exact", header + "-\t0\t" + strings.Repeat("a", 65536-len(header)-5) + "\n", false, true},
		{"budget exceeded", header + "-\t0\t" + strings.Repeat("a", 65537-len(header)-5) + "\n", false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			present, err := launchListContains(tc.raw, "target")
			if (err == nil) != tc.valid || present != tc.present {
				t.Fatal("unexpected presence result", present, err)
			}
		})
	}
}

func TestInspectLaunchAgentSeparatesAbsenceFromFailure(t *testing.T) {
	expected, err := os.ReadFile("../../testdata/contracts/launch-agent.sample.plist")
	if err != nil {
		t.Fatal(err)
	}
	label := "dev.siq.agent-security." + strings.Repeat("a", 64)
	for _, name := range []string{"absent", "loaded", "running", "enumeration failure", "malformed", "disappeared", "foreign config", "wrong domain", "mismatched expectation"} {
		t.Run(name, func(t *testing.T) {
			queries, details := 0, 0
			control := func(args ...string) (string, error) {
				switch strings.Join(args, " ") {
				case "manageruid":
					if name == "wrong domain" {
						return "502", nil
					}
					return "501", nil
				case "managername":
					return "Aqua", nil
				case "list":
					queries++
					if name == "enumeration failure" {
						return "PID\tStatus\tLabel\n", errors.New("failure")
					}
					if name == "malformed" {
						return "", nil
					}
					if name == "absent" {
						return "PID\tStatus\tLabel\n", nil
					}
					return "PID\tStatus\tLabel\n-\t0\t" + label + "\n", nil
				case "list -x " + label:
					details++
					if name == "disappeared" {
						return "", errors.New("missing")
					}
					if name == "foreign config" {
						return strings.Replace(string(expected), "<string>serve</string>", "<string>other</string>", 1), nil
					}
					if name == "running" {
						xml := string(expected)
						at := strings.LastIndex(xml, "</dict>")
						return xml[:at] + "<key>PID</key><integer>123</integer>" + xml[at:], nil
					}
					return string(expected), nil
				default:
					t.Fatal("unexpected command", args)
					return "", nil
				}
			}
			input := expected
			if name == "mismatched expectation" {
				input = []byte(strings.Replace(string(expected), label, label+"x", 1))
			}
			loaded, pid, err := inspectLaunchAgent(control, 501, label, input)
			valid := name == "absent" || name == "loaded" || name == "running"
			if (err == nil) != valid || loaded != (name == "loaded" || name == "running") {
				t.Fatal(loaded, pid, err)
			}
			if (name == "running" && pid != 123) || (name != "running" && pid != 0) {
				t.Fatal("unexpected PID", pid)
			}
			if (name == "absent" || name == "enumeration failure" || name == "malformed") && details != 0 {
				t.Fatal("queried unconfirmed target")
			}
			if (name == "wrong domain" || name == "mismatched expectation") && queries != 0 {
				t.Fatal("unsafe enumeration")
			}
		})
	}
}
