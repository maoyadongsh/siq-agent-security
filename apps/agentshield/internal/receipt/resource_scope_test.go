package receipt

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestFilesystemSymlinkCannotEscapeGrantOrExplicitDeny(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows canonical path contract requires native host validation")
	}
	base := t.TempDir()
	root := filepath.Join(base, "granted")
	outside := filepath.Join(base, "outside")
	blocked := filepath.Join(root, "blocked")
	for _, dir := range []string{root, outside, blocked} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	insideFile := filepath.Join(root, "inside.txt")
	outsideFile := filepath.Join(outside, "outside.txt")
	for _, file := range []string{insideFile, outsideFile, filepath.Join(blocked, "denied.txt")} {
		if err := os.WriteFile(file, []byte("fixture"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	for name, target := range map[string]string{
		"escape-file": outsideFile,
		"escape-dir":  outside,
		"inside-link": insideFile,
		"deny-link":   blocked,
		"dangling":    filepath.Join(base, "missing-target"),
	} {
		if err := os.Symlink(target, filepath.Join(root, name)); err != nil {
			t.Skipf("symlinks unavailable: %v", err)
		}
	}
	g := &grant.Grant{Facts: []grant.Fact{
		scopedFact("allow-root", "filesystem", "fs.read", filepath.ToSlash(root), "allow"),
		scopedFact("deny-blocked", "filesystem", "fs.read", filepath.ToSlash(blocked), "deny"),
	}}
	for _, tc := range []struct {
		name, target string
		want         bool
	}{
		{"inside", insideFile, true},
		{"inside_link", filepath.Join(root, "inside-link"), true},
		{"outside_file_alias", filepath.Join(root, "escape-file"), false},
		{"outside_dir_alias_missing_tail", filepath.Join(root, "escape-dir", "new.txt"), false},
		{"explicit_deny_alias", filepath.Join(root, "deny-link", "denied.txt"), false},
		{"dangling_alias", filepath.Join(root, "dangling"), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, ok := pathGranted(g, filepath.ToSlash(tc.target), false)
			if ok != tc.want {
				t.Fatalf("pathGranted(%q) = %t, want %t", tc.target, ok, tc.want)
			}
		})
	}
	writeGrant := &grant.Grant{Facts: []grant.Fact{
		scopedFact("allow-write", "filesystem", "fs.write", filepath.ToSlash(root), "allow"),
	}}
	for _, tc := range []struct {
		name, target string
		want         bool
	}{
		{"new_file_inside", filepath.Join(root, "new.txt"), true},
		{"new_file_through_outside_alias", filepath.Join(root, "escape-dir", "new.txt"), false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, ok := pathGranted(writeGrant, filepath.ToSlash(tc.target), true)
			if ok != tc.want {
				t.Fatalf("write pathGranted(%q) = %t, want %t", tc.target, ok, tc.want)
			}
		})
	}
}

func TestFilesystemRootScopeRemainsValid(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows root paths require native path-identity validation")
	}
	target := filepath.ToSlash(filepath.Join(t.TempDir(), "inside.txt"))
	g := &grant.Grant{Facts: []grant.Fact{
		scopedFact("root-read", "filesystem", "fs.read", "/", "allow"),
	}}
	if id, ok := pathGranted(g, target, false); !ok || id != "root-read" {
		t.Fatalf("root Grant lost its documented lexical scope: id=%q allowed=%t", id, ok)
	}
	g.Facts = append(g.Facts, scopedFact("root-deny", "filesystem", "fs.read", "/", "deny"))
	if _, ok := pathGranted(g, target, false); ok {
		t.Fatal("explicit root deny did not override allow")
	}
}

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

func TestWebExtractAuthorizesEveryURL(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	g.Facts = append(g.Facts,
		scopedFact("extract", "tool", "tool.invoke", "web_extract", "allow"),
		scopedFact("search", "tool", "tool.invoke", "web_search", "allow"),
	)
	fx := newFixture(t, "block", g, false)
	allow := map[string]map[string]any{
		"one":      map[string]any{"urls": []any{"https://api.github.com/a"}},
		"object":   map[string]any{"urls": []any{map[string]any{"url": "https://api.github.com/a", "href": "https://evil.example/secret"}}},
		"href":     map[string]any{"urls": []any{map[string]any{"href": "https://api.github.com/a"}}},
		"with_url": map[string]any{"url": "https://api.github.com/a", "urls": []any{"https://api.github.com/b"}},
	}
	for name, params := range allow {
		d, err := fx.eng.Decide(req("hermes", "web_extract", params))
		if err != nil || d.Action != ActionAllow {
			t.Fatalf("%s: %+v %v", name, d, err)
		}
		if len(d.Receipt.ResourceRefs) == 0 {
			t.Fatalf("%s receipt did not bind a network resource", name)
		}
	}
	deny := map[string]map[string]any{
		"second_host": map[string]any{"urls": []any{"https://api.github.com/a", "https://evil.example/b"}},
		"decoy_url":   map[string]any{"url": "https://api.github.com/a", "urls": []any{"https://evil.example/b"}},
		"file":        map[string]any{"urls": []any{"file:///tmp/secret"}},
		"empty":       map[string]any{"urls": []any{}},
		"string":      map[string]any{"urls": "https://api.github.com/a"},
		"number":      map[string]any{"urls": []any{1}},
		"bad_object":  map[string]any{"urls": []any{map[string]any{"url": 1, "href": "https://api.github.com/a"}}},
		"search":      map[string]any{"query": "api.github.com"},
	}
	for name, params := range deny {
		tool := "web_extract"
		if name == "search" {
			tool = "web_search"
		}
		d, err := fx.eng.Decide(req("hermes", tool, params))
		if err != nil || d.Action != ActionDeny {
			t.Fatalf("%s: %+v %v", name, d, err)
		}
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
