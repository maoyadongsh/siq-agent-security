package server

import (
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestLocalFailureIsNotAnOnlineDecision(t *testing.T) {
	rows := []receipt.Receipt{{RecordType: "local_failure", Action: "deny"}, {RecordType: "local_failure", Action: "unknown"}, {RecordType: "decision", Action: "deny"}}
	view := summarizeActivity(rows, taskActivityItem{}, []int{0, 1, 2})
	if view.Decisions["deny"] != 1 || view.Decisions["other"] != 0 || view.Decisions["allow"] != 0 {
		t.Fatal("local failure promoted into policy decision counts")
	}
}
