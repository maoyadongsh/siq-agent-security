package server

import (
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func TestSkillInstallStageRequestVersionBoundary(t *testing.T) {
	v1 := `{"schema_version":"local-skill-install-stage-create/v1","request_id":"is-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","grant_id":"fixture","expected_revision":0,"instance_id":"hi-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","directory_name":"example","actor_id":"human"}`
	v2 := strings.Replace(v1, "stage-create/v1", "stage-create/v2", 1)
	v2 = strings.TrimSuffix(v2, "}") + `,"target_id":"sit-` + strings.Repeat("c", 64) + `"}`
	for name, raw := range map[string]string{"v1": v1, "v2": v2} {
		t.Run(name, func(t *testing.T) {
			w := httptest.NewRecorder()
			r := httptest.NewRequest("POST", "/", strings.NewReader(raw))
			var request skillinstall.Request
			if !readInstallStageRequest(w, r, &request) {
				t.Fatal("valid version rejected", w.Body.String())
			}
			if (request.TargetID != "") != (name == "v2") {
				t.Fatal("version lost its target identity")
			}
		})
	}
	for name, raw := range map[string]string{
		"v1-empty-target":   strings.TrimSuffix(v1, "}") + `,"target_id":""}`,
		"v1-v2-target":      strings.Replace(v2, "stage-create/v2", "stage-create/v1", 1),
		"v2-missing-target": strings.Replace(v1, "stage-create/v1", "stage-create/v2", 1),
		"v2-null-target":    strings.TrimSuffix(strings.Replace(v1, "stage-create/v1", "stage-create/v2", 1), "}") + `,"target_id":null}`,
		"duplicate-version": `{"schema_version":"local-skill-install-stage-create/v1",` + v2[1:],
		"cased-target":      strings.Replace(v2, "target_id", "Target_ID", 1),
		"caller-path":       strings.TrimSuffix(v2, "}") + `,"root":"C:/foreign"}`,
		"future-version":    strings.Replace(v2, "stage-create/v2", "stage-create/v99", 1),
	} {
		t.Run(name, func(t *testing.T) {
			w := httptest.NewRecorder()
			r := httptest.NewRequest("POST", "/", strings.NewReader(raw))
			var request skillinstall.Request
			if readInstallStageRequest(w, r, &request) || w.Code != 400 {
				t.Fatal("ambiguous version or caller scope accepted")
			}
		})
	}
}
