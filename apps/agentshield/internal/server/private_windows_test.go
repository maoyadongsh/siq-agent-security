package server

import (
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestWindowsServerRejectsCachedCredentialsAfterACLDrift(t *testing.T) {
	for _, name := range []string{"root", "token", "admin-recovery.token", "keys", "keys/signing.seed"} {
		t.Run(name, func(t *testing.T) {
			s, st := newServer(t, "block")
			var err error
			s.d.Token, err = st.Token()
			if err != nil {
				t.Fatal(err)
			}
			s.d.RecoveryToken, err = st.RecoveryToken()
			if err != nil {
				t.Fatal(err)
			}
			seed := filepath.Join(st.Dir, "keys", "signing.seed")
			if err := os.WriteFile(seed, []byte(base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{3}, 32))), 0600); err != nil {
				t.Fatal(err)
			}
			key, err := signing.LoadExisting(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			s.d.CheckPrivateState = func() error {
				if err := st.CheckPrivateCredentials(); err != nil {
					return err
				}
				return key.CheckPrivateStorage()
			}
			if w := sessionRequest(t, s, "GET", "/v1/status", nil, s.bootAdmin, nil, nil); w.Code != 200 {
				t.Fatal("private fixture rejected", w.Code)
			}
			path := filepath.Join(st.Dir, filepath.FromSlash(name))
			if name == "root" {
				path = st.Dir
			}
			restore := acltest.BroadenRead(t, st.Dir, path)
			beforeSeq, beforeHead := s.d.Chain.Head()
			beforePair, beforeDeadline := s.pairHash, s.pairDeadline
			for _, request := range []struct{ method, path, bearer string }{
				{"GET", "/v1/status", s.bootAdmin},
				{"POST", "/v1/decide", s.d.Token},
				{"POST", "/v1/session/pairing", s.d.RecoveryToken},
				{"POST", "/v1/pair", ""},
			} {
				w := sessionRequest(t, s, request.method, request.path, nil, request.bearer, nil, map[string]string{"X-SIQ-Local-CLI": "1"})
				if w.Code != 503 || strings.TrimSpace(w.Body.String()) != `{"error":"state_private_permissions"}` {
					t.Fatal("unsafe storage reached handler", request.path, w.Code)
				}
			}
			afterSeq, afterHead := s.d.Chain.Head()
			if beforeSeq != afterSeq || beforeHead != afterHead || beforePair != s.pairHash || beforeDeadline != s.pairDeadline {
				t.Fatal("rejected request changed authority or receipts")
			}
			if _, err := New(s.d); err == nil {
				t.Fatal("unsafe storage accepted at startup")
			}
			restore()
			if w := sessionRequest(t, s, "GET", "/v1/status", nil, s.bootAdmin, nil, nil); w.Code != 200 {
				t.Fatal("restored test fixture rejected", w.Code)
			}
		})
	}
}
