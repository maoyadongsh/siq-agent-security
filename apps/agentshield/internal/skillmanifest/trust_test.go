package skillmanifest

import (
	"strings"
	"testing"
)

func TestReleaseVerificationRejectsSelfSignedManifest(t *testing.T) {
	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts(), SignedBy: k.PublicBase64()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	if err := Verify(m); err == nil {
		t.Fatal("untrusted self-signed issuer was accepted as a release")
	}
	if err := VerifyWithPublicKey(m, k.Public()); err != nil {
		t.Fatalf("explicit development signing self-check must remain available: %v", err)
	}
	m.SignedBy = ReleasePublicKeyB64
	if err := Verify(m); err == nil {
		t.Fatal("relabeling an untrusted signature as the release issuer must not work")
	}
	if err := VerifyWithPublicKey(m, nil); err == nil {
		t.Fatal("missing external trust anchor accepted")
	}
}
