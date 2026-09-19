package adapters

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func workBuddySourceInput(t *testing.T, event string) string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "..", "packages", "contracts", "fixtures", "workbuddy_command_hook_input_v1_source_examples.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	return string(fixture[event])
}

func TestWorkBuddyManagedSourceMetadata(t *testing.T) {
	for _, event := range []string{"pre", "post"} {
		t.Run(event, func(t *testing.T) {
			input := workBuddySourceInput(t, event)
			if _, err := ParseWorkBuddyManagedInput(strings.NewReader(input)); err != nil {
				t.Fatalf("source-derived %s fixture rejected: %v", event, err)
			}
			d := &workBuddyDecider{action: "allow"}
			out := WorkBuddyManagedHook(strings.NewReader(input), d, "hri-fixture", "block", "")
			if out.HookSpecificOutput.PermissionDecision != "" || len(d.requests) != 1 {
				t.Fatalf("source-derived %s fixture did not reach its decision/observation: %+v", event, out)
			}
			mutated := input
			for _, field := range []string{"generation_id", "model", "client", "version"} {
				var obj map[string]any
				if err := json.Unmarshal([]byte(mutated), &obj); err != nil {
					t.Fatal(err)
				}
				obj[field] = "changed-descriptive-metadata"
				raw, err := json.Marshal(obj)
				if err != nil {
					t.Fatal(err)
				}
				mutated = string(raw)
			}
			d2 := &workBuddyDecider{action: "allow"}
			WorkBuddyManagedHook(strings.NewReader(mutated), d2, "hri-fixture", "block", "")
			if len(d2.requests) != 1 || !reflect.DeepEqual(d.requests[0], d2.requests[0]) || d.session != d2.session {
				t.Fatal("descriptive metadata altered the Authority request")
			}
		})
	}
}

func TestWorkBuddyManagedSourceMetadataBounds(t *testing.T) {
	for _, field := range []string{"generation_id", "model", "client", "version"} {
		t.Run(field, func(t *testing.T) {
			with := func(value string) string {
				return strings.TrimSuffix(workBuddyInput, "}") + `,"` + field + `":` + value + `}`
			}
			for _, value := range []string{`""`, `"` + strings.Repeat("x", 4096) + `"`, `"` + strings.Repeat("界", 1365) + `x"`} {
				if _, err := ParseWorkBuddyManagedInput(strings.NewReader(with(value))); err != nil {
					t.Fatalf("valid byte boundary rejected: %v", err)
				}
			}
			for _, value := range []string{`null`, `true`, `42`, `[]`, `{}`, `" leading"`, `"trailing "`, `"x\ny"`, `"` + strings.Repeat("x", 4097) + `"`, `"` + strings.Repeat("界", 1366) + `"`} {
				bad := with(value)
				if _, err := ParseWorkBuddyManagedInput(strings.NewReader(bad)); err == nil {
					t.Fatalf("invalid metadata accepted: field=%s length=%d", field, len(value))
				}
				for _, mode := range []string{"block", "warn", "audit_only"} {
					d := &workBuddyDecider{action: "allow"}
					out := WorkBuddyManagedHook(strings.NewReader(bad), d, "hri-fixture", mode, "")
					if out.HookSpecificOutput.PermissionDecision != "deny" || len(d.events) != 0 {
						t.Fatal("invalid metadata reached Authority")
					}
				}
			}
			good := with(`"metadata"`)
			for _, bad := range []string{
				strings.TrimSuffix(good, "}") + `,"` + field + `":"again"}`,
				strings.TrimSuffix(good, "}") + `,"\u` + "00" + string("0123456789abcdef"[field[0]>>4]) + string("0123456789abcdef"[field[0]&15]) + field[1:] + `":"again"}`,
				strings.Replace(good, `"`+field+`":`, `"`+strings.ToUpper(field)+`":`, 1),
				strings.TrimSuffix(good, "}") + `,"retry_of":"forged"}`,
				good + `{}`,
			} {
				if _, err := ParseWorkBuddyManagedInput(strings.NewReader(bad)); err == nil {
					t.Fatal("duplicate, alias, unknown or trailing metadata accepted")
				}
			}
		})
	}
}
