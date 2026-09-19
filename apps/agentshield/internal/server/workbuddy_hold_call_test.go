package server

import (
	"strings"
	"testing"
)

func TestWorkBuddyRuntimeHoldCallProtocol(t *testing.T) {
	first := "workbuddy-call/v1:" + strings.Repeat("a", 64)
	next := "workbuddy-call/v1:" + strings.Repeat("b", 64)
	for _, path := range []string{"/v1/decide", "/v1/observe", "/v1/hold-status", "/v1/hold-executions/reserve", "/v1/hold-executions/status"} {
		t.Run(path, func(t *testing.T) {
			field := "tool_call_id"
			extra := ""
			if strings.HasPrefix(path, "/v1/hold-executions/") {
				field = "retry_tool_call_id"
			}
			if strings.HasSuffix(path, "/reserve") {
				extra = `,"original_tool_call_id":"` + first + `"`
			}
			good := `{"` + field + `":"` + next + `"` + extra + `,"params":{"path":"C:\\synthetic"}}`
			if !workBuddyRuntimeCall(path, []byte(good)) {
				t.Fatal("valid native call rejected")
			}
			for _, bad := range []string{
				strings.Replace(good, next, "raw-call", 1),
				strings.Replace(good, `"`+next+`"`, "null", 1),
				strings.Replace(good, field, strings.ToUpper(field), 1),
				strings.TrimSuffix(good, "}") + `,"` + field + `":"` + next + `"}`,
				strings.Replace(good, `"params":{`, `"params":{"path":"duplicate",`, 1),
				good + `{}`,
			} {
				if workBuddyRuntimeCall(path, []byte(bad)) {
					t.Fatal("ambiguous or invalid call accepted")
				}
			}
			if extra != "" {
				for _, bad := range []string{strings.Replace(good, first, next, 1), strings.Replace(good, first, "old-raw-call", 1), strings.Replace(good, "original_tool_call_id", "Original_tool_call_id", 1), strings.TrimSuffix(good, "}") + `,"original_tool_call_\u0069d":"` + first + `"}`} {
					if workBuddyRuntimeCall(path, []byte(bad)) {
						t.Fatal("invalid original retry correlation accepted")
					}
				}
			}
		})
	}
}
