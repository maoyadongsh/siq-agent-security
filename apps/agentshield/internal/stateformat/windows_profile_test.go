package stateformat

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestWindowsProfileContractRoundTrip(t *testing.T) {
	raw, err := os.ReadFile("../../testdata/contracts/local-state-windows-profile-plan.json")
	if err != nil {
		t.Fatal(err)
	}
	var p WindowsProfilePlan
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	encoded := EncodeWindowsProfilePlan(p)
	got, err := DecodeWindowsProfilePlan(encoded)
	if err != nil || got != p {
		t.Fatal("valid plan round trip", err)
	}
	for _, mutate := range []func(*WindowsProfilePlan){
		func(p *WindowsProfilePlan) { p.Profile = "posix/v1" },
		func(p *WindowsProfilePlan) { p.MigrationHash = "unknown" },
		func(p *WindowsProfilePlan) {
			p.TargetMarker = strings.Replace(p.TargetMarker, `"min_reader":3`, `"min_reader":2`, 1)
		},
		func(p *WindowsProfilePlan) {
			p.TargetMarker = strings.Replace(p.TargetMarker, strings.Repeat("b", 64), strings.Repeat("c", 64), 1)
		},
		func(p *WindowsProfilePlan) {
			p.SourceMarker = strings.Replace(p.SourceMarker, `"min_writer":2`, `"min_writer":3`, 1)
		},
		func(p *WindowsProfilePlan) {
			p.SourceMarker = strings.Replace(p.SourceMarker, `"min_writer":2`, `"min_writer":2,"min_writer":2`, 1)
		},
	} {
		bad := p
		mutate(&bad)
		if _, err := DecodeWindowsProfilePlan(EncodeWindowsProfilePlan(bad)); err == nil {
			t.Fatal("invalid transition accepted")
		}
	}
	for _, bad := range [][]byte{append(encoded, []byte("{}")...), []byte(strings.Replace(string(encoded), `"schema":`, `"SCHEMA":`, 1)), []byte(strings.Replace(string(encoded), `"schema":`, `"unknown":0,"schema":`, 1))} {
		if _, err := DecodeWindowsProfilePlan(bad); err == nil {
			t.Fatal("ambiguous wire accepted")
		}
	}
	raw, err = os.ReadFile("../../testdata/contracts/local-state-windows-profile-done.json")
	var d WindowsProfileDone
	if err != nil || DecodeObject(raw, []string{"schema", "plan_sha256", "marker_sha256"}, &d) != nil || d.Schema != "state-windows-profile-done/v1" || !Digest(d.Plan) || !Digest(d.Marker) {
		t.Fatal("done fixture")
	}
}
