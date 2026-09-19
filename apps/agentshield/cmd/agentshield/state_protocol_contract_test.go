package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestStateProtocolCLIContractFixtures(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "state")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	var out bytes.Buffer
	if e := cmdStateStatus(nil, &out); e != nil {
		t.Fatal(e)
	}
	check := func(name string) {
		t.Helper()
		fixture, e := os.ReadFile("../../testdata/contracts/" + name + ".json")
		if e != nil {
			t.Fatal(e)
		}
		var a, b any
		if json.Unmarshal(out.Bytes(), &a) != nil || json.Unmarshal(fixture, &b) != nil || !reflect.DeepEqual(a, b) {
			t.Fatal("CLI contract differs", name)
		}
	}
	check("local-state-status-reader3")
	if _, e := os.Lstat(dir); !os.IsNotExist(e) {
		t.Fatal("diagnosis created state")
	}
	out.Reset()
	if e := cmdInitialize(nil, &out); e != nil {
		t.Fatal(e)
	}
	out.Reset()
	if e := cmdStateMigrate([]string{"--confirm"}, &out); e != nil {
		t.Fatal(e)
	}
	check("local-state-migration-result")
}
