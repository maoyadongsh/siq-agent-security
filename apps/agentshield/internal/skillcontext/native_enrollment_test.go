package skillcontext

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

func TestSignedEnrollmentSelectsMandatoryEnginePath(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, kind := range []string{"complete", "missing-call", "missing-session", "missing-identity", "artifact-drift", "revoked", "legacy"} {
			t.Run(mode+"/"+kind, func(t *testing.T) {
				f := newCallFixture(t)
				base := f.grants["grt-agent-baseline"]
				base.HermesToolsetAllowlist = &[]string{"read_file"}
				base.Facts = []grant.Fact{{FactID: "fixture-read", Domain: "filesystem", Action: "fs.read", Resource: admission.Resource{Type: "path", Value: "/workspace"}, Effect: "allow", State: "declared", Authority: "skill_manifest", EvidenceIDs: []string{"synthetic"}}}
				f.signGrant(base)
				authority, err := intent.Open(f.s.dir, f.key, func(id string) (*grant.Grant, int, error) {
					g, ok := f.grants[id]
					if !ok {
						return nil, 0, os.ErrNotExist
					}
					return g, 1, nil
				})
				if err != nil {
					t.Fatal(err)
				}
				identities, err := runtimeidentity.Open(f.s.dir, f.key, authority, func(id string) (string, error) {
					if id != testInstance {
						return "", os.ErrNotExist
					}
					return "hermes", nil
				})
				if err != nil {
					t.Fatal(err)
				}
				create := runtimeidentity.CreateRequest{SchemaVersion: "local-runtime-identity-create/v3", InstanceID: testInstance, GrantID: base.GrantID, ExpectedGrantRevision: 1, ActorID: "fixture-human", SessionTTLSeconds: 300, NativeSkillPolicy: &runtimeidentity.NativeSkillPolicy{Mode: "required", RuntimeArtifactSHA256: strings.Repeat("8", 64)}}
				if kind == "artifact-drift" {
					create.NativeSkillPolicy.RuntimeArtifactSHA256 = strings.Repeat("9", 64)
				}
				if kind == "legacy" {
					create.SchemaVersion = "local-runtime-identity-create/v1"
					create.NativeSkillPolicy = nil
				}
				identity, err := identities.Create(create)
				if err != nil {
					t.Fatal(err)
				}
				f.instances[testInstance] = identity
				if kind != "missing-session" {
					f.register()
				}
				call := f.callRequest("call-1", nil)
				if kind != "missing-call" && kind != "missing-session" {
					f.bind(call)
				}
				if kind == "revoked" {
					if _, err := identities.Revoke(identity.IdentityID, "fixture-human"); err != nil {
						t.Fatal(err)
					}
				}
				if kind == "missing-identity" {
					if err := os.Remove(filepath.Join(f.s.dir, "runtime-identities", identity.IdentityID+".json")); err != nil {
						t.Fatal(err)
					}
				}
				lookup, err := f.calls.RequiredLookup(identities)
				if err != nil {
					t.Fatal(err)
				}
				request := receipt.Request{Platform: "hermes", AgentID: testAgent, SessionID: testSession, RuntimeTaskID: testTask, Tool: call.Tool, ToolCallID: call.ToolCallID, Params: call.Params}
				required, verified, lookupErr := lookup(request)
				if kind == "legacy" {
					if required || verified != nil || lookupErr != nil {
						t.Fatal("legacy enrollment changed")
					}
					return
				}
				if !required {
					t.Fatal("native call absence downgraded required policy")
				}
				pack, _ := rulepack.Builtin()
				chain, err := receipt.OpenChain(t.TempDir(), "local", f.key)
				if err != nil {
					t.Fatal(err)
				}
				engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, EnforcementMode: mode, Now: func() time.Time { return f.now }, NativeCalls: lookup, IntentLookup: func(_, _, _ string) (*receipt.IntentContract, error) {
					return &receipt.IntentContract{IntentID: "fixture-intent", TaskID: "trusted-envelope", Principal: "fixture-user", AgentID: testAgent, Purpose: "native enrollment fixture", AllowedEffects: []string{"file.read"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "fixture-revision", SelectedGrant: base}, nil
				}})
				if err != nil {
					t.Fatal(err)
				}
				d, err := engine.Decide(request)
				if err != nil {
					t.Fatal(err)
				}
				if kind == "complete" {
					if d.Action != receipt.ActionAllow || d.Receipt.NativeInvocation == nil {
						t.Fatal("verified enrollment did not permit native call", d)
					}
				} else if d.Action != receipt.ActionDeny {
					t.Fatal("unavailable native call was not hard denied", d)
				}
			})
		}
	}
}
