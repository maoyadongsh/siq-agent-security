package server

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/adapters"
)

func TestAdapterPreflightErrorsPreserveSafeCategory(t *testing.T) {
	for _, code := range []string{"workbuddy_config_path_invalid", "workbuddy_config_mismatch", "workbuddy_state_incompatible", "workbuddy_config_parent_unavailable", "workbuddy_config_file_unavailable", "workbuddy_credential_parent_unavailable", "workbuddy_credential_file_unavailable", "workbuddy_credential_invalid"} {
		t.Run(code, func(t *testing.T) {
			w := httptest.NewRecorder()
			adapterError(w, fmt.Errorf("private-path-and-token: %w", &adapters.WorkBuddyPreflightError{Code: code, ObjectCode: "private-path-and-token"}))
			var body map[string]any
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
				t.Fatal(err)
			}
			if w.Code != 409 || body["code"] != code || body["recovery_required"] != false || !strings.Contains(fmt.Sprint(body["error"]), "预检未通过") {
				t.Fatal(w.Code, body)
			}
			if strings.Contains(w.Body.String(), "private-path-and-token") {
				t.Fatal("private error detail leaked")
			}
		})
	}
}

func TestAdapterPreflightDoesNotHideRecoveryOrExposeUnknownErrors(t *testing.T) {
	preflight := &adapters.WorkBuddyPreflightError{Code: "workbuddy_config_file_unavailable"}
	for _, tc := range []struct {
		err      error
		status   int
		recovery bool
	}{
		{errors.Join(adapterinstall.ErrRecoveryRequired, preflight), 409, true},
		{errors.Join(adapterinstall.ErrPlanChanged, preflight), 409, false},
		{&adapters.WorkBuddyPreflightError{Code: "private-path-and-token"}, 400, false},
		{errors.New("private-path-and-token"), 400, false},
	} {
		w := httptest.NewRecorder()
		adapterError(w, tc.err)
		var body map[string]any
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatal(err)
		}
		if w.Code != tc.status || body["recovery_required"] != tc.recovery || body["code"] != nil {
			t.Fatal(w.Code, body)
		}
		if strings.Contains(w.Body.String(), "private-path-and-token") {
			t.Fatal("private error detail leaked")
		}
	}
}
