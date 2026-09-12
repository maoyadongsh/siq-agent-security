package main

import (
	"encoding/xml"
	"io"
	"os"
	"strings"
	"testing"
)

const launchFixtureBinary = `/Users/example/SIQ & tools/agent "quoted" $bin`
const launchFixtureState = `/Users/example/Library/Application Support/SIQ <local> 中文`

func TestLaunchAgentPlistFixtureAndEscaping(t *testing.T) {
	text, err := renderLaunchAgent(launchFixtureBinary, launchFixtureState, strings.Repeat("a", 64))
	if err != nil {
		t.Fatal(err)
	}
	decoder := xml.NewDecoder(strings.NewReader(text))
	values := []string{}
	for {
		token, err := decoder.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		if start, ok := token.(xml.StartElement); ok && start.Name.Local == "string" {
			var value string
			if err := decoder.DecodeElement(&value, &start); err != nil {
				t.Fatal(err)
			}
			values = append(values, value)
		}
	}
	if len(values) != 6 || values[1] != launchFixtureBinary || values[2] != "serve" || values[3] != launchFixtureState {
		t.Fatal("XML changed arguments or injected values", values)
	}
	fixture := "../../testdata/contracts/launch-agent.sample.plist"
	if os.Getenv("SIQ_UPDATE_LAUNCH_AGENT_FIXTURE") == "1" {
		if err := os.WriteFile(fixture, []byte(text), 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if string(expected) != text {
		t.Fatal("plist fixture drift")
	}
	other, err := renderLaunchAgent(launchFixtureBinary, launchFixtureState, strings.Repeat("b", 64))
	if err != nil || other == text {
		t.Fatal("instances share label")
	}
}
func TestLaunchAgentRejectsAmbiguousInput(t *testing.T) {
	id := strings.Repeat("a", 64)
	for _, bad := range []string{"relative", "/Users/test/../other", "/Users/test\narg", "/Users/test\x00arg", "/Users/test\xff", "/Users/test\ufffe"} {
		if _, err := renderLaunchAgent(bad, "/state", id); err == nil {
			t.Fatal("invalid executable accepted")
		}
		if _, err := renderLaunchAgent("/program", bad, id); err == nil {
			t.Fatal("invalid state path accepted")
		}
	}
	for _, bad := range []string{"", strings.Repeat("A", 64), strings.Repeat("z", 64)} {
		if _, err := renderLaunchAgent("/program", "/state", bad); err == nil {
			t.Fatal("invalid instance accepted")
		}
	}
}
