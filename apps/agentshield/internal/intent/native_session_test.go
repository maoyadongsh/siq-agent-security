package intent

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

func TestOpenClawNativeEpochIdentityAndBinding(t *testing.T) {
	first, err := OpenClawSessionID("agent:fixture:main", "11111111-1111-4111-8111-111111111111")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/openclaw-native-session.json")
	if err != nil {
		t.Fatal(err)
	}
	var vector string
	if json.Unmarshal(raw, &vector) != nil || vector != first {
		t.Fatal("encoded identity differs from contract vector")
	}
	again, _ := OpenClawSessionID("agent:fixture:main", "11111111-1111-4111-8111-111111111111")
	next, _ := OpenClawSessionID("agent:fixture:main", "22222222-2222-4222-8222-222222222222")
	if first != again || first == next {
		t.Fatal("native epoch identity not stable and isolated")
	}
	s := testStore(t)
	c := testContract()
	c.Agent.Platform = "openclaw"
	signed, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Bind(Binding{Platform: "openclaw", AgentID: c.Agent.ID, SessionID: first, IntentID: signed.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	// Reconstruct an old signed record as historical input, bypassing the new
	// writer exactly once. It must remain readable but never resolve at runtime.
	legacy := b
	legacy.SessionID = "agent:fixture:main"
	legacy.BindingID = bindingID(legacy.Platform, legacy.SessionID, legacy.AgentID)
	legacy.Signature, err = s.key.SignCanonical(bindingMap(legacy))
	if err != nil {
		t.Fatal(err)
	}
	legacyPath, err := s.bindingPath(legacy.BindingID)
	if err != nil {
		t.Fatal(err)
	}
	legacyRaw, _ := json.Marshal(legacy)
	if err = publish(legacyPath, legacyRaw); err != nil {
		t.Fatal(err)
	}
	if stored, err := s.GetBinding(legacy.BindingID); err != nil || stored.Signature != legacy.Signature {
		t.Fatal("historical signature changed", err)
	}
	if _, got, err := s.ResolveBinding("openclaw", again, c.Agent.ID); err != nil || got == nil || got.Signature != b.Signature {
		t.Fatal("same epoch lost binding", err)
	}
	if _, got, err := s.ResolveBinding("openclaw", next, c.Agent.ID); err != nil || got != nil {
		t.Fatal("new epoch borrowed old binding", err)
	}
	if _, _, err := s.ResolveBinding("openclaw", "agent:fixture:main", c.Agent.ID); err == nil {
		t.Fatal("raw key resolved")
	}
	if _, err := s.Bind(Binding{Platform: "openclaw", AgentID: c.Agent.ID, SessionID: "agent:fixture:main", IntentID: signed.IntentID}); err == nil {
		t.Fatal("legacy raw binding minted")
	}
}

func TestOpenClawNativeEpochRejectsAmbiguousInputs(t *testing.T) {
	epoch := "11111111-1111-4111-8111-111111111111"
	for _, key := range []string{"", "with\x00nul", "with\x7fdel", strings.Repeat("a", 257), string([]byte{0xff})} {
		if _, err := OpenClawSessionID(key, epoch); err == nil {
			t.Fatal("bad key accepted")
		}
	}
	for _, value := range []string{"", "default", "AAAAAAAA-1111-4111-8111-111111111111", epoch + " "} {
		if _, err := OpenClawSessionID("key", value); err == nil {
			t.Fatal("bad epoch accepted")
		}
	}
	for _, value := range []string{"agent:fixture:main", "openclaw-default", "openclaw-session/v2:" + strings.Repeat("a", 64), "openclaw-session/v1:" + strings.Repeat("A", 64), "openclaw-session/v1:" + strings.Repeat("a", 63)} {
		if err := ValidateNativeSession("openclaw", value); err == nil {
			t.Fatal("bad encoded session accepted")
		}
	}
	if err := ValidateNativeSession("hermes", "native-1"); err != nil {
		t.Fatal("unrelated host changed")
	}
}
