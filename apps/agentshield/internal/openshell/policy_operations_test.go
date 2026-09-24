package openshell

import (
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestApplyPreservesCompleteStaticPolicyAndExtensions(t *testing.T) {
	vectors := loadPolicySafetyVectors(t)
	base := vectors.ReadCases[0].Output
	active := base
	var submitted map[string]any
	client := New(Options{
		PollInterval:      -1,
		policyCoordinator: newPolicyCoordinator(),
		Runner: func(args []string) (int, string, string) {
			if eq(args, "policy", "get", "shared", "--full") {
				return 0, active, ""
			}
			if len(args) >= 5 && args[0] == "policy" && args[1] == "set" {
				raw, err := os.ReadFile(args[4])
				if err != nil {
					t.Fatal(err)
				}
				parsed, err := parseYAML(string(raw))
				if err != nil {
					t.Fatal(err)
				}
				submitted = asMap(parsed)
				active = policyOutput("11", string(raw))
				return 0, "Policy version 11 submitted (hash: c0ffee11)", ""
			}
			return 1, "", "unexpected"
		},
	})
	receipt, err := client.ApplyNetwork("shared", []NetworkRule{{
		Endpoint: "mirror.example.com:8443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
	}}, "7")
	if err != nil {
		t.Fatal(err)
	}
	landlock := asMap(submitted["landlock"])
	extension := asMap(submitted["x_siq_extension"])
	if landlock["compatibility"] != "hard_requirement" || landlock["abi"] != 6 || extension["mode"] != "yes" {
		t.Fatalf("static policy was not preserved: landlock=%v extension=%v", landlock, extension)
	}
	if receipt.BasePolicyDigest != vectors.ReadCases[0].PolicyDigest || receipt.AppliedPolicyDigest == receipt.BasePolicyDigest {
		t.Fatalf("receipt did not bind full policy transition: %+v", receipt)
	}
}

func TestApplyRejectsUnsupportedNetworkRulesBeforeWrite(t *testing.T) {
	base := testdata(t, "policy_get_full.txt")
	tests := []NetworkRule{
		{Endpoint: "api.example.com:443", Effect: "deny", BinaryPaths: []string{"/usr/bin/curl"}},
		{Endpoint: "api.example.com:443", Effect: "allow"},
		{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"bin/curl"}},
		{Endpoint: "api.example.com:443/admin", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}},
	}
	for index, rule := range tests {
		writes := 0
		client := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
			if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
				return 0, base, ""
			}
			if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
				writes++
			}
			return 1, "", "unexpected"
		}})
		if _, err := client.ApplyNetwork("s1", []NetworkRule{rule}, "1"); err == nil {
			t.Fatalf("case %d must reject", index)
		}
		if writes != 0 {
			t.Fatalf("case %d wrote an unsupported policy", index)
		}
	}
}

func TestApplyRequiresExplicitCanonicalExpectedRevision(t *testing.T) {
	for _, revision := range []string{"", "0", "01", " latest ", "2.0"} {
		calls := 0
		client := New(Options{policyCoordinator: newPolicyCoordinator(), Runner: func([]string) (int, string, string) {
			calls++
			return 1, "", "unexpected"
		}})
		_, err := client.ApplyNetwork("s1", nil, revision)
		if err == nil || calls != 0 {
			t.Fatalf("revision %q: err=%v calls=%d", revision, err, calls)
		}
	}
}

func TestApplyDetectsPrewriteAndPostwriteDrift(t *testing.T) {
	base := testdata(t, "policy_get_full.txt")
	baseBody := policyBody(t, base)
	for _, stage := range []string{"prewrite", "postwrite"} {
		reads := 0
		writes := 0
		client := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
			if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
				reads++
				if stage == "prewrite" && reads == 2 {
					return 0, policyOutput("3", baseBody), ""
				}
				if stage == "postwrite" && writes > 0 {
					return 0, policyOutput("4", baseBody), ""
				}
				return 0, base, ""
			}
			if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
				writes++
				return 0, "Policy version 2 submitted (hash: c0ffee)", ""
			}
			return 1, "", "unexpected"
		}})
		_, err := client.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
		if err == nil {
			t.Fatalf("%s drift must reject", stage)
		}
		if stage == "prewrite" && writes != 0 {
			t.Fatal("prewrite drift must be zero-write")
		}
	}
}

func TestTargetPolicyWritesAreSerializedAcrossClients(t *testing.T) {
	base := testdata(t, "policy_get_full.txt")
	active := base
	coordinator := newPolicyCoordinator()
	var runnerMu sync.Mutex
	concurrentSets := 0
	maxConcurrentSets := 0
	setCalls := 0
	runner := func(args []string) (int, string, string) {
		runnerMu.Lock()
		defer runnerMu.Unlock()
		if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
			concurrentSets++
			if concurrentSets > maxConcurrentSets {
				maxConcurrentSets = concurrentSets
			}
			setCalls++
			raw, _ := os.ReadFile(args[4])
			time.Sleep(5 * time.Millisecond)
			active = policyOutput("2", string(raw))
			concurrentSets--
			return 0, "Policy version 2 submitted (hash: cafe)", ""
		}
		return 1, "", "unexpected"
	}
	clients := []*Client{
		New(Options{Runner: runner, PollInterval: -1, policyCoordinator: coordinator}),
		New(Options{Runner: runner, PollInterval: -1, policyCoordinator: coordinator}),
	}
	errs := make(chan error, 2)
	for _, client := range clients {
		go func(client *Client) {
			_, err := client.ApplyNetwork("s1", []NetworkRule{{Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
			errs <- err
		}(client)
	}
	first, second := <-errs, <-errs
	if (first == nil) == (second == nil) {
		t.Fatalf("exactly one write should win: first=%v second=%v", first, second)
	}
	if setCalls != 1 || maxConcurrentSets != 1 {
		t.Fatalf("sets=%d max_concurrent=%d", setCalls, maxConcurrentSets)
	}
	if first != nil && !strings.Contains(first.Error(), "revision conflict") || second != nil && !strings.Contains(second.Error(), "revision conflict") {
		t.Fatalf("loser must observe revision conflict: first=%v second=%v", first, second)
	}
}

func TestRollbackDetectsPrewriteAndPostwriteDrift(t *testing.T) {
	for _, stage := range []string{"prewrite", "postwrite"} {
		t.Run(stage, func(t *testing.T) {
			base := testdata(t, "policy_get_full.txt")
			active := base
			setCalls := 0
			client := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
				if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
					return 0, active, ""
				}
				if len(args) >= 2 && args[0] == "policy" && args[1] == "set" {
					setCalls++
					raw, err := os.ReadFile(args[4])
					if err != nil {
						t.Fatal(err)
					}
					if setCalls == 1 {
						active = policyOutput("9", string(raw))
						return 0, "Policy version 9 submitted (hash: a11ce123)", ""
					}
					if stage == "postwrite" {
						active = policyOutput("16", string(raw))
						return 0, "Policy version 15 submitted (hash: bacc1234)", ""
					}
					active = policyOutput("15", string(raw))
					return 0, "Policy version 15 submitted (hash: bacc1234)", ""
				}
				return 1, "", "unexpected"
			}})
			receipt, err := client.ApplyNetwork("s1", []NetworkRule{{
				Endpoint: "api.example.com:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"},
			}}, "1")
			if err != nil {
				t.Fatal(err)
			}
			_, err = client.RollbackAuthorized("s1", receipt, func(RollbackAuthorization) error {
				if stage == "prewrite" {
					active = policyOutput("10", policyBody(t, base))
				}
				return nil
			})
			if err == nil {
				t.Fatal("rollback drift must fail closed")
			}
			if stage == "prewrite" && setCalls != 1 {
				t.Fatal("prewrite drift must not perform rollback write")
			}
			if stage == "postwrite" && setCalls != 2 {
				t.Fatal("postwrite drift must be detected after the attempted restore")
			}
		})
	}
}

func TestClearNetworkMatchesGatewayEmptyOmissionWithoutIgnoringDrift(t *testing.T) {
	for _, tamper := range []bool{false, true} {
		active := testdata(t, "policy_get_full.txt") + "network_policies:\n  original:\n    endpoints:\n    - host: api.example.com\n      port: 443\n    binaries:\n    - path: /usr/bin/curl\n"
		writes := 0
		client := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
			if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
				return 0, active, ""
			}
			if len(args) >= 5 && args[0] == "policy" && args[1] == "set" {
				writes++
				raw, err := os.ReadFile(args[4])
				if err != nil {
					t.Fatal(err)
				}
				parsed, err := parseYAML(string(raw))
				if err != nil {
					t.Fatal(err)
				}
				doc := asMap(parsed)
				if len(asMap(doc["network_policies"])) == 0 {
					delete(doc, "network_policies")
				}
				if tamper {
					doc["unexpected_change"] = true
				}
				active = policyOutput("2", dumpYAML(doc))
				return 0, "Policy version 2 submitted (hash: cafe)", ""
			}
			return 1, "", "unexpected"
		}})
		receipt, err := client.ApplyNetwork("s1", []NetworkRule{}, "1")
		if tamper {
			if err == nil {
				t.Fatal("extra policy change must not be hidden by empty omission")
			}
			continue
		}
		if err != nil {
			t.Fatal(err)
		}
		snapshot, err := client.ReadEffective("s1")
		if err != nil {
			t.Fatal(err)
		}
		if len(snapshot.Network) != 0 || receipt.AppliedPolicyDigest != snapshot.PolicyDigest || writes != 1 {
			t.Fatal("empty intent not verified")
		}
		_, err = client.ApplyNetwork("s1", []NetworkRule{}, "2")
		if err != nil || writes != 1 {
			t.Fatal("already empty intent should not write again")
		}
	}
}

func TestEmptyNetworkFormsAreNoOp(t *testing.T) {
	for _, suffix := range []string{"", "network_policies: {}\n"} {
		full := testdata(t, "policy_get_full.txt") + suffix
		client := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
			if len(args) >= 4 && args[0] == "policy" && args[1] == "get" {
				return 0, full, ""
			}
			t.Fatalf("already-empty policy must not write: %v", args[:2])
			return 1, "", "unexpected"
		}})
		before, err := client.ReadEffective("s1")
		if err != nil {
			t.Fatal(err)
		}
		receipt, err := client.ApplyNetwork("s1", nil, before.Revision)
		if err != nil {
			t.Fatal(err)
		}
		if receipt.Result != "no_op" || receipt.BackendRevision != before.Revision || receipt.AppliedPolicyDigest != before.PolicyDigest {
			t.Fatal("already-empty policy must preserve its exact revision and digest")
		}
	}
}
