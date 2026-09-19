package runtimeidentity

import (
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/statefs"
)

func assertPrivateIdentityFile(t *testing.T, path string) {
	t.Helper()
	if err := statefs.CheckPrivateFile(path); err != nil {
		t.Fatal("private file", err)
	}
}
func broadenIdentityFile(t *testing.T, root, path string) {
	t.Helper()
	acltest.BroadenRead(t, root, path)
}

func TestWindowsIdentityCachedCredentialRejectsACLDrift(t *testing.T) {
	for _, scope := range []string{"root", "secret-directory", "secret"} {
		t.Run(scope, func(t *testing.T) {
			s, req, _ := fixture(t)
			r, token := create(t, s, req)
			if _, err := s.Authenticate(token); err != nil {
				t.Fatal(err)
			}
			path, _ := s.CredentialPath(r.IdentityID)
			if scope == "root" {
				path = s.dir
			}
			if scope == "secret-directory" {
				path = filepath.Dir(path)
			}
			restore := acltest.BroadenRead(t, s.dir, path)
			if _, err := s.Authenticate(token); err == nil {
				t.Fatal("cached identity accepted unsafe storage")
			}
			if _, err := s.Enroll(token, "native-after-acl-drift"); err == nil {
				t.Fatal("unsafe storage minted session")
			}
			restore()
			if _, err := s.Authenticate(token); err != nil {
				t.Fatal("restored test fixture rejected", err)
			}
		})
	}
}
