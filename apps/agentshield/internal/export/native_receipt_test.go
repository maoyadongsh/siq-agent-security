package export

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func nativeReceiptFixture(t *testing.T, sample string) receipt.Receipt {
	t.Helper()
	raw, err := os.ReadFile("../../testdata/contracts/" + sample)
	if err != nil {
		t.Fatal(err)
	}
	var r receipt.Receipt
	if err := json.Unmarshal(raw, &r); err != nil {
		t.Fatal(err)
	}
	return r
}

func TestNativeReceiptExportPreservesSourceIntegrityAndPrivacy(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	for _, name := range []string{"native-receipt-with-skill-v3.sample.json", "native-receipt-no-skill-v3.sample.json"} {
		t.Run(name, func(t *testing.T) {
			r := nativeReceiptFixture(t, name)
			all := []receipt.Receipt{r}
			if err := receipt.Verify(all, key.Public()); err != nil {
				t.Fatal("product fixture", err)
			}
			bundle := Build(Input{Key: key, Snap: ledger.Snapshot{Receipts: all}})
			if !bundle.ChainPrefixValid || bundle.HistoryIntegrity != receipt.HistoryUnknown || len(bundle.Receipts) != 1 || bundle.Receipts[0].Hash != r.Hash {
				t.Fatal("source integrity/projection changed")
			}
			if err := Seal(key, &bundle); err != nil {
				t.Fatal(err)
			}
			if err := Verify(key.Public(), bundle); err != nil {
				t.Fatal(err)
			}
			if bundle.DerivedFrom.AttestationScope != AttestationShareProjectionOnly {
				t.Fatal("export promoted authority")
			}
			raw, err := MarshalJSONBytes(bundle)
			if err != nil {
				t.Fatal(err)
			}
			for _, private := range []string{"native_invocation", r.NativeInvocation.CallID, r.NativeInvocation.SessionRegistrationID, r.NativeInvocation.CallSignature, r.NativeInvocation.AgentAuthority.GrantID, "never-persist-this", "skill_attribution"} {
				if bytes.Contains(raw, []byte(private)) {
					t.Fatalf("private native evidence exported: %s", private)
				}
			}
			// Original source hash authenticates all native evidence; changing only
			// the new proof must invalidate the source even if the projection omits it.
			all[0].NativeInvocation.RequestBinding = strings.Repeat("f", 64)
			tampered := Build(Input{Key: key, Snap: ledger.Snapshot{Receipts: all}})
			if tampered.ChainPrefixValid || tampered.ChainVerified {
				t.Fatal("tampered native proof verified")
			}
		})
	}
}

func TestNativeActivityProjectionVerifiesFullProofBeforeSelecting(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	r := nativeReceiptFixture(t, "native-receipt-with-skill-v3.sample.json")
	// A separately signed synthetic activity envelope makes the test receipt
	// eligible for activity projection. It does not create runtime authorization.
	r.IntentDigest = strings.Repeat("a", 64)
	chain, err := receipt.OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	all, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	scope := receipt.TaskActivityKey{ChainID: r.ChainID, Platform: r.Platform, SessionID: r.SessionID, AgentID: *r.AgentID, TaskID: r.TaskID, IntentID: r.IntentID, IntentDigest: r.IntentDigest}
	projection, err := ProjectActivity(all, key.Public(), nil, scope, 1)
	if err != nil || len(projection.Rows) != 1 || projection.Rows[0].SourceHash != r.Hash {
		t.Fatal("native activity missing", err)
	}
	raw, err := json.Marshal(projection)
	if err != nil {
		t.Fatal(err)
	}
	for _, private := range []string{r.NativeInvocation.CallID, r.NativeInvocation.SessionRegistrationID, r.SkillAttribution.SkillID, "never-persist-this", "native_invocation"} {
		if bytes.Contains(raw, []byte(private)) {
			t.Fatal("native activity leaked private evidence")
		}
	}
	all[0].NativeInvocation.Contexts[0].Authority.GrantDigest = strings.Repeat("f", 64)
	if _, err := ProjectActivity(all, key.Public(), nil, scope, 1); err == nil {
		t.Fatal("changed native authority projected")
	}
}
