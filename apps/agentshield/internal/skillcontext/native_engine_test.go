package skillcontext

import (
	"encoding/json"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/contractfixture"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
)

// Exercise the signed stores and actual decision engine together. Host facts
// remain controlled callbacks; this is not the native Hermes acceptance test.
func TestNativeStoreEngineIntegrationAndContractSamples(t *testing.T) {
	for _, withSkill := range []bool{false, true} {
		name := "no-skill"
		if withSkill {
			name = "with-skill"
		}
		t.Run(name, func(t *testing.T) {
			f := newCallFixture(t)
			for _, g := range f.grants {
				g.DefaultEffect = "deny"
				g.HermesToolsetAllowlist = &[]string{"read_file"}
				g.Facts = []grant.Fact{{FactID: "fixture-read", Domain: "filesystem", Action: "fs.read", Resource: admission.Resource{Type: "path", Value: "/workspace"}, Effect: "allow", State: "declared", Authority: "skill_manifest", EvidenceIDs: []string{"synthetic"}}}
				f.signGrant(g)
			}
			f.register()
			var context *InvocationContext
			if withSkill {
				context = f.issueV2(f.request(1, nil))
			}
			r := f.callRequest("call-1", context)
			f.bind(r)
			pack, err := rulepack.Builtin()
			if err != nil {
				t.Fatal(err)
			}
			chain, err := receipt.OpenChain(t.TempDir(), "local", f.key)
			if err != nil {
				t.Fatal(err)
			}
			engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Version: "native-component-fixture", EnforcementMode: "block", Now: func() time.Time { return f.now },
				NativeCalls: func(req receipt.Request) (bool, *receipt.NativeInvocationVerification, error) {
					v, err := f.calls.VerifyNativeForEngine(req)
					return true, v, err
				},
				IntentLookup: func(_, _, _ string) (*receipt.IntentContract, error) {
					return &receipt.IntentContract{IntentID: "fixture-intent", TaskID: "trusted-envelope", Principal: "synthetic-user", AgentID: testAgent,
						Purpose: "read synthetic fixture", AllowedEffects: []string{"file.read"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "fixture-revision", SelectedGrant: f.grants["grt-agent-baseline"]}, nil
				},
			})
			if err != nil {
				t.Fatal(err)
			}
			req := receipt.Request{Platform: r.Subject.Platform, SessionID: r.Subject.SessionID, AgentID: r.Subject.AgentID, RuntimeTaskID: r.Subject.TaskID, Tool: r.Tool, ToolCallID: r.ToolCallID, Params: r.Params}
			d, err := engine.Decide(req)
			if err != nil || d.Action != receipt.ActionAllow || d.Receipt.SchemaVersion != "runtime-receipt/v3" {
				t.Fatalf("store->engine failed: %v %+v", err, d)
			}
			b, err := json.MarshalIndent(d.Receipt, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			b = append(b, '\n')
			p := filepath.Join("../../testdata/contracts", "native-receipt-"+name+"-v3.sample.json")
			if os.Getenv("AGENTSHIELD_UPDATE_NATIVE_RECEIPTS") == "1" {
				if err := os.WriteFile(p, b, 0644); err != nil {
					t.Fatal(err)
				}
			}
			want, err := os.ReadFile(p)
			if err != nil {
				t.Fatal(err)
			}
			var historical receipt.Receipt
			if err = json.Unmarshal(want, &historical); err != nil || receipt.Verify([]receipt.Receipt{historical}, f.key.Public()) != nil {
				t.Fatal("historical native receipt invalid", err)
			}
			if same, err := contractfixture.EqualReceiptContent(b, want); err != nil || !same {
				t.Fatal("native receipt sample content drift", err)
			}
			rows, err := chain.Read()
			if err != nil || receipt.Verify(rows, f.key.Public()) != nil {
				t.Fatal("v3 chain verification failed", err)
			}
			f.hostCallErr = errMissing
			req.ToolCallID = "call-after-revoke"
			d, err = engine.Decide(req)
			if err != nil || d.Action != receipt.ActionDeny || d.Receipt.AuthorityStatus != "invalid" {
				t.Fatal("missing live call did not deny", err)
			}
		})
	}
}
