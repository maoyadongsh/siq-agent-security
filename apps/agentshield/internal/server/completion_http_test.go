package server

import "testing"

func TestCompletionHTTPAuthorityAndAmbiguity(t *testing.T) {
	s, _ := newServer(t, "block")
	effectCall(t, s, "GET", "/v1/tasks/unknown/completion", token, nil, 403)
	effectCall(t, s, "GET", "/v1/tasks/unknown/completion", s.bootAdmin, nil, 404)
	effectCall(t, s, "POST", "/v1/tasks/task-1/completion", s.bootAdmin, map[string]any{"completed": true}, 405)
	c := apiIntent()
	effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, c, 201)
	out := effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 200)
	if out["status"] != "unknown" || out["reason_code"] != "not_required" || out["schema_version"] != "completion-status/v1" {
		t.Fatal(out)
	}
	c.IntentID = "other-intent"
	effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, c, 201)
	effectCall(t, s, "GET", "/v1/tasks/task-1/completion", s.bootAdmin, nil, 409)
}
