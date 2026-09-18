package adapterinstall

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestWorkBuddyManagedRepairRestoresCoverageWithoutChangingUserHooks(t *testing.T) {
	o := Options{Platform: WorkBuddy, StateDir: "/test-state", Home: "/test-home"}
	old, command := workBuddyManagedCommand("old-siq", o), workBuddyManagedCommand("new-siq", o)
	user := map[string]any{"type": "command", "command": "user-tool", "timeout": 12}
	foreign := map[string]any{"type": "prompt", "command": command}
	original := []any{
		map[string]any{"matcher": "Read", "metadata": "user value", "hooks": []any{
			map[string]any{"type": "command", "command": old, "async": true, "timeout": 1}, user, foreign,
		}},
		map[string]any{"matcher": "Write", "hooks": []any{
			map[string]any{"type": "command", "command": command},
			map[string]any{"type": "command", "command": hookCommand("old-siq", WorkBuddy, o.StateDir)},
		}},
	}
	before, _ := json.Marshal(original)
	if hostHookRegisteredCommand(map[string]any{"hooks": map[string]any{"PreToolUse": original, "PostToolUse": original}}, command) {
		t.Fatal("restricted hooks must not satisfy registration")
	}
	got := upsertWorkBuddyManagedHook(original, command, o, "old-siq")
	want := []any{
		map[string]any{"matcher": "Read", "metadata": "user value", "hooks": []any{user, foreign}},
		map[string]any{"matcher": ".*", "hooks": []any{map[string]any{"type": "command", "command": command, "timeout": 5}}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("repair must preserve user scope and replace all owned hooks: %#v", got)
	}
	if !hostHookRegisteredCommand(map[string]any{"hooks": map[string]any{"PreToolUse": got, "PostToolUse": got}}, command) {
		t.Fatal("repaired hooks do not cover pre and post events")
	}
	after, _ := json.Marshal(original)
	if string(before) != string(after) {
		t.Fatal("repair changed the captured input")
	}
	if !reflect.DeepEqual(upsertWorkBuddyManagedHook(got, command, o, "new-siq"), want) {
		t.Fatal("repair is not idempotent")
	}
}
