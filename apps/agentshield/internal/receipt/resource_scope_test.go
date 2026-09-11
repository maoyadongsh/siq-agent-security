package receipt

import (
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestSecretRedactionCannotBypassResourceOrApprovalScope(t *testing.T) {
	for _, tc := range []struct {
		name, endpoint string
		approve        bool
		want           string
	}{
		{"granted", "https://api.github.com/report", false, ActionRedact},
		{"wrong_host", "https://evil.example/report", false, ActionDeny},
		{"wrong_port", "https://api.github.com:8443/report", false, ActionDeny},
		{"requires_approval", "https://api.github.com/report", true, ActionDeny},
	} {
		t.Run(tc.name, func(t *testing.T) {
			g := deployedGrant(t, "hermes", true)
			if tc.approve {
				for i := range g.Facts {
					if g.Facts[i].Domain == "tool" && g.Facts[i].Resource.Value == "web_fetch" {
						g.Facts[i].Conditions = map[string]any{"require_approval": true}
					}
				}
			}
			fx := newFixture(t, "block", g, false)
			d, err := fx.eng.Decide(req("hermes", "web_fetch", map[string]any{"url": tc.endpoint, "auth": "sk-" + strings.Repeat("A", 30)}))
			if err != nil || d.Action != tc.want {
				t.Fatal("redaction changed authority boundary", err, d.Action)
			}
			if tc.want == ActionDeny && d.Params != nil {
				t.Fatal("denied operation returned executable replacement params")
			}
		})
	}
}

func scopedFact(id, domain, action, resource, effect string) grant.Fact {
	return grant.Fact{FactID: id, Domain: domain, Action: action, Resource: admission.Resource{Type: "path", Value: resource}, Effect: effect, State: "declared", Authority: "human"}
}

func TestExplicitGrantFilesystemBoundariesAcrossModes(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, tc := range []struct {
			name, tool, path string
			allowed          bool
		}{
			{"read_allowed", "read_file", "/work/readonly/report", true},
			{"read_space", "read_file", "/work/readonly/report with spaces", true},
			{"readonly_cannot_write", "write_file", "/work/readonly/report", false},
			{"readonly_cannot_delete", "delete_file", "/work/readonly/report", false},
			{"write_allowed", "write_file", "/work/output/report", true},
			{"read_write_includes_read", "read_file", "/work/output/report", true},
			{"read_outside_denied", "read_file", "/outside/report", false},
			{"sibling_prefix_denied", "read_file", "/work/readonly-evil/report", false},
			{"traversal_denied", "read_file", "/work/readonly/../../outside/report", false},
			{"deny_overrides_parent", "read_file", "/work/readonly/private/report", false},
			{"write_deny_overrides_parent", "write_file", "/work/output/private/report", false},
			{"credential_deny_overrides_directory", "read_file", "/work/readonly/.env", false},
			{"missing_target", "read_file", "", false},
			{"relative_target", "read_file", "report", false},
		} {
			t.Run(mode+"/"+tc.name, func(t *testing.T) {
				g := deployedGrant(t, "hermes", false)
				tools := []string{"read_file", "write_file", "delete_file"}
				g.HermesToolsetAllowlist = &tools
				g.Facts = []grant.Fact{
					scopedFact("ro", "filesystem", "fs.read", "/work/readonly", "allow"),
					scopedFact("rw", "filesystem", "fs.write", "/work/output", "allow"),
					scopedFact("ro-deny", "filesystem", "fs.read", "/work/readonly/private", "deny"),
					scopedFact("rw-deny", "filesystem", "fs.write", "/work/output/private", "deny"),
				}
				fx := newFixture(t, mode, g, false)
				d, err := fx.eng.Decide(req("hermes", tc.tool, map[string]any{"path": tc.path}))
				if err != nil {
					t.Fatal(err)
				}
				want := ActionAllow
				if !tc.allowed && mode == "block" {
					want = ActionDeny
				}
				if d.Action != want {
					t.Fatalf("action %s, want %s", d.Action, want)
				}
				if !tc.allowed && mode != "block" && (d.Receipt.AdvisoryAction == nil || *d.Receipt.AdvisoryAction != ActionDeny) {
					t.Fatal("policy mode lost deny advisory")
				}
				if tc.allowed && len(d.Receipt.MatchedFactIDs) == 0 {
					t.Fatal("allowed without matched resource")
				}
			})
		}
	}
}

func TestNetworkGrantExactPortsDenyAndStructuredTargets(t *testing.T) {
	for _, tc := range []struct {
		name, url string
		allowed   bool
	}{
		{"allowed", "https://api.example.test/report", true},
		{"explicit_port", "https://api.example.test:443/report", true},
		{"normalized_host", "https://API.EXAMPLE.TEST./report", true},
		{"wrong_port", "https://api.example.test:8443/report", false},
		{"wrong_default_port", "http://api.example.test/report", false},
		{"subdomain", "https://child.example.test/report", true},
		{"root_not_subdomain", "https://example.test/report", false},
		{"deny_before_allow", "https://private.example.test/report", false},
		{"lookalike", "https://example.test.evil/report", false},
		{"userinfo", "https://api.example.test@evil.test/report", false},
		{"port_zero", "https://api.example.test:0/report", false},
		{"missing_port_value", "https://api.example.test:/report", false},
		{"missing_target", "", false},
		{"ipv6", "http://[::1]:8080/report", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			g := deployedGrant(t, "hermes", false)
			g.Facts = []grant.Fact{
				scopedFact("deny", "network", "http.request", "private.example.test:443", "deny"),
				scopedFact("net", "network", "http.request", "*.example.test:443", "allow"),
				scopedFact("v6", "network", "http.request", "[::1]:8080", "allow"),
			}
			fx := newFixture(t, "block", g, false)
			d, err := fx.eng.Decide(req("hermes", "web_fetch", map[string]any{"url": tc.url, "body": "https://api.example.test/report"}))
			if err != nil {
				t.Fatal(err)
			}
			if (d.Action == ActionAllow) != tc.allowed {
				t.Fatalf("unexpected action %s: %s", d.Action, tc.name)
			}
		})
	}
}

func TestUnscopedAndUnsupportedGrantResourcesFailClosed(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	g.Facts = nil
	fx := newFixture(t, "block", g, false)
	if d, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/work/report"})); err != nil || d.Action != ActionDeny {
		t.Fatal("tool-only grant read arbitrary file")
	}
	for _, pattern := range []string{"api.example.test", "api.example.test:443/private/**", "api.example.test:0", "api.example.test:65536", "*"} {
		g.Facts = []grant.Fact{scopedFact("net", "network", "http.request", pattern, "allow")}
		if _, ok := hostGranted(g, "api.example.test:443"); ok {
			t.Fatal("unsupported network scope widened", pattern)
		}
	}
	g.Facts = []grant.Fact{scopedFact("allow", "network", "http.request", "api.example.test:443", "allow"), scopedFact("unsupported-deny", "network", "http.request", "api.example.test:443/private/**", "deny")}
	if _, ok := hostGranted(g, "api.example.test:443"); ok {
		t.Fatal("unsupported deny was ignored")
	}
}

func TestRedactionCannotMixConcurrentGrantIdentities(t *testing.T) {
	g := deployedGrant(t, "hermes", true)
	newGrant := *g
	newGrant.GrantID += "-replacement"
	fx := newFixture(t, "block", g, false)
	calls := 0
	fx.eng.opts.Grants = func(_, _ string) *grant.Grant {
		calls++
		if calls == 1 {
			return g
		}
		return &newGrant
	}
	d, err := fx.eng.Decide(req("hermes", "web_fetch", map[string]any{"url": "https://api.github.com/report", "auth": "sk-" + strings.Repeat("A", 30)}))
	if err != nil || d.Action != ActionDeny || d.Params != nil {
		t.Fatal("mixed Grant identities during redaction", err)
	}
}

func TestImportedGrantCannotUseImplicitAuthorityInAnyMode(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			g := deployedGrant(t, "hermes", false)
			g.AdmissionID = "adm-si-" + strings.Repeat("a", 64)
			fx := newFixture(t, mode, g, false)
			out, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/work/report"}))
			if err != nil || out.Action != ActionDeny || out.Receipt.AuthorityStatus != "invalid" || out.Receipt.ReasonCode != "intent_grant_installation_binding_required" {
				t.Fatal("implicit import escaped fixed authority", out, err)
			}
		})
	}
}
