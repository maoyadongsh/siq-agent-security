package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestOfflineGrantActionsCannotBypassImportedSource(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	pack, err := loadPack()
	if err != nil {
		t.Fatal(err)
	}
	imports, err := skillimport.Open(dir, key, pack, Version)
	if err != nil {
		t.Fatal(err)
	}
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: cli-permission\ndescription: Read a report.\n---\nRead a report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	id := "si-" + strings.Repeat("a", 32)
	if _, _, _, err := imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	_, derived, err := imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	prepared, err := grant.BuildImported(derived.Admission, grant.Options{Key: key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: "hri-fixture"}}, "human", "ip-"+strings.Repeat("b", 32))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.CommitGrant(state.GrantCommit{Grant: prepared.Grant, DesiredPolicy: prepared.DesiredPolicy, ExpectedRevision: -1, Audit: &state.AuditEvent{Event: "fixture_prepare", Target: prepared.Grant.GrantID}}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "skill-imports", "blobs", id, "payload", "SKILL.md"), []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, verb := range []string{"challenge", "approve"} {
		if err := cmdGrantAction(st, key, verb, []string{prepared.Grant.GrantID}); !errors.Is(err, skillimport.ErrChanged) {
			t.Fatal("CLI source check bypass", verb, err)
		}
	}
	if err := cmdGrantAction(st, key, "deploy", []string{prepared.Grant.GrantID}); !errors.Is(err, grant.ErrImportInstallationRequired) {
		t.Fatal("CLI early activation", err)
	}
}
