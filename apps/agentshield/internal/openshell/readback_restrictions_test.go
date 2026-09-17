package openshell

import "testing"

func TestReadbackRestrictionsCannotBroadenOnReapply(t *testing.T) {
	cases := map[string]map[string]any{
		"method_path": {"rules": []any{map[string]any{"allow": map[string]any{"method": "GET", "path": "/safe/**"}}}},
		"ips":         {"allowed_ips": []any{"192.0.2.1/32"}},
		"protocol":    {"protocol": "rest"}, "enforcement": {"enforcement": "enforce"},
		"rewrite_true":  {"request_body_credential_rewrite": true},
		"rewrite_false": {"request_body_credential_rewrite": false}, "plain": {},
	}
	for name, extra := range cases {
		t.Run(name, func(t *testing.T) {
			endpoint := map[string]any{"host": "example.test", "port": 443}
			for k, v := range extra {
				endpoint[k] = v
			}
			policy := map[string]any{"version": 1, "network_policies": map[string]any{"r": map[string]any{
				"endpoints": []any{endpoint}, "binaries": []any{map[string]any{"path": "/usr/bin/curl"}},
			}}}
			body := dumpYAML(policy)
			writes := 0
			c := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
				if len(args) > 1 && args[0] == "policy" && args[1] == "get" {
					return 0, policyOutput("1", body), ""
				}
				writes++
				return 1, "", "unexpected write"
			}})
			snap, err := c.ReadEffective("fixture")
			if err != nil {
				t.Fatal(err)
			}
			if len(snap.Network) != 1 {
				t.Fatalf("missing projection: %+v", snap)
			}
			r := snap.Network[0]
			if name == "plain" {
				if _, err := networkRulesToGateway(snap.Network); err != nil {
					t.Fatal(err)
				}
				if !c.Verify("fixture", DeploymentReceipt{BackendRevision: "1", AppliedPolicyDigest: snap.PolicyDigest}, []string{r.Endpoint}, nil).Passed {
					t.Fatal("plain readback should pass")
				}
				return
			}
			if !r.hasReadbackRestrictions() {
				t.Fatal("restriction silently lost")
			}
			if want, ok := extra["request_body_credential_rewrite"]; ok && (r.RequestBodyCredentialRewrite == nil || *r.RequestBodyCredentialRewrite != want) {
				t.Fatal("rewrite presence/value lost")
			}
			if name == "method_path" && (r.Method != "GET" || r.Path != "/safe/**") {
				t.Fatal("L7 restrictions lost")
			}
			if name == "ips" && (len(r.AllowedIPs) != 1 || r.AllowedIPs[0] != "192.0.2.1/32") {
				t.Fatal("IP restriction lost")
			}
			if _, err := c.ApplyNetwork("fixture", snap.Network, "1"); err == nil {
				t.Fatal("restricted reapply must reject")
			}
			for _, allow := range []bool{true, false} {
				var allows, denies []string
				if allow {
					allows = []string{r.Endpoint}
				} else {
					denies = []string{r.Endpoint}
				}
				rep := c.Verify("fixture", DeploymentReceipt{BackendRevision: "1", AppliedPolicyDigest: snap.PolicyDigest}, allows, denies)
				if rep.Passed || rep.Level != VerifyFailed {
					t.Fatal("endpoint-only verification overstated restricted access")
				}
			}
			if writes != 0 {
				t.Fatalf("rejection mutated backend: %d", writes)
			}
		})
	}
}

func TestApplyRejectsPartialRestrictionFields(t *testing.T) {
	f := false
	for _, r := range []NetworkRule{
		{Method: "GET"}, {Path: "/"}, {AllowedIPs: []string{}}, {Protocol: "rest"},
		{Enforcement: "enforce"}, {RequestBodyCredentialRewrite: &f},
	} {
		r.Endpoint = "example.test:443"
		r.Effect = "allow"
		r.BinaryPaths = []string{"/usr/bin/curl"}
		if _, err := networkRulesToGateway([]NetworkRule{r}); err == nil {
			t.Fatalf("restriction dropped: %+v", r)
		}
	}
}
