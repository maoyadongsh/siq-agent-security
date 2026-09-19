package server

import (
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestWindowsResourceConfirmationRejectsAmbiguousWireBeforeState(t *testing.T) {
	st, err := state.Open(filepath.Join(t.TempDir(), "state"))
	if err != nil {
		t.Fatal(err)
	}
	s := &Server{d: Deps{Store: st}}
	valid := `{"schema_version":"grant-resource-edit/v2","expected_revision":0,"actor_id":"operator","tools":["read_file"],"network":[],"filesystem":{"read_only":["C:/Approved"],"read_write":[]},"models":[],"confirm_filesystem_profile":true}`
	for _, test := range []struct {
		name, body string
		status     int
	}{
		{"requires-state-activation", valid, 409},
		{"case-alias", strings.Replace(valid, `"confirm_filesystem_profile"`, `"Confirm_Filesystem_Profile"`, 1), 400},
		{"nested-case-alias", strings.Replace(valid, `"read_only"`, `"Read_Only"`, 1), 400},
		{"duplicate-confirmation", `{"confirm_filesystem_profile":false,` + valid[1:], 400},
		{"null-confirmation", strings.Replace(valid, `:true}`, `:null}`, 1), 400},
		{"null-path-array", strings.Replace(valid, `["C:/Approved"]`, `null`, 1), 400},
	} {
		t.Run(test.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			r := httptest.NewRequest("POST", "/v1/grants/test/resources", strings.NewReader(test.body))
			s.editGrantResources(w, r, grant.Grant{}, 0)
			if w.Code != test.status {
				t.Fatalf("status %d: %s", w.Code, w.Body.String())
			}
			if test.status == 409 && !strings.Contains(w.Body.String(), "windows_profile_activation_required") {
				t.Fatal("wrong state diagnosis", w.Body.String())
			}
		})
	}
}
