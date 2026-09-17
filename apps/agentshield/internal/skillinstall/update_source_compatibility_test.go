package skillinstall

import (
	"bytes"
	"context"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func TestSaveUpdateSourcePreservesIncompatibleRecords(t *testing.T) {
	for _, kind := range []string{"future_schema", "unknown_field", "bad_signature", "invalid_status", "wrong_install", "malformed_json"} {
		t.Run(kind, func(t *testing.T) {
			f, op := installedInspection(t)
			s := f.store
			gitifyImportRecord(t, f)
			if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", true)); err != nil {
				t.Fatal(err)
			}
			path := s.updateSourcePath(op.InstallID)
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			value, err := canon.Decode(raw)
			if err != nil {
				t.Fatal(err)
			}
			doc := value.(map[string]any)
			switch kind {
			case "future_schema":
				doc["schema_version"] = "local-skill-update-schedule/v99"
			case "unknown_field":
				doc["future_policy"] = "preserve"
			case "invalid_status":
				doc["last_status"] = "checking"
			case "wrong_install":
				doc["install_id"] = "sin-" + strings.Repeat("f", 64)
			}
			delete(doc, "signature")
			signature, err := s.key.SignCanonical(doc)
			if err != nil {
				t.Fatal(err)
			}
			if kind == "bad_signature" {
				signature = strings.Repeat("0", 128)
			}
			doc["signature"] = signature
			before, err := canon.Marshal(doc)
			if err != nil {
				t.Fatal(err)
			}
			if kind == "malformed_json" {
				before = []byte("{broken")
			}
			if err := os.WriteFile(path, before, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := s.ReadUpdateSchedule(context.Background(), op.InstallID); !errors.Is(err, ErrChanged) {
				t.Fatalf("fixture must be rejected on read: %v", err)
			}
			pathsBefore := storeTree(t, s.dir)
			for _, enabled := range []bool{false, true} {
				if _, err := s.SaveUpdateSource(context.Background(), op.InstallID, saveRequest("", enabled)); !errors.Is(err, ErrChanged) {
					t.Fatalf("save(enable=%v) must refuse incompatible record: %v", enabled, err)
				}
				after, err := os.ReadFile(path)
				if err != nil || !bytes.Equal(before, after) {
					t.Fatalf("rejected save changed original bytes: %v", err)
				}
				if !reflect.DeepEqual(pathsBefore, storeTree(t, s.dir)) {
					t.Fatal("rejected save changed state path listing")
				}
			}
			if _, err := s.DisableUpdateSource(context.Background(), op.InstallID, disableRequest()); !errors.Is(err, ErrChanged) {
				t.Fatalf("disable must refuse incompatible record: %v", err)
			}
			after, err := os.ReadFile(path)
			if err != nil || !bytes.Equal(before, after) {
				t.Fatalf("rejected disable changed original bytes: %v", err)
			}
			if !reflect.DeepEqual(pathsBefore, storeTree(t, s.dir)) {
				t.Fatal("rejected disable changed state path listing")
			}
		})
	}
}
