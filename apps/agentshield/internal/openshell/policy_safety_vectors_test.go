package openshell

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

type policySafetyVectors struct {
	Schema    string `json:"schema"`
	ReadCases []struct {
		Name         string          `json:"name"`
		Expect       string          `json:"expect"`
		Output       string          `json:"output"`
		Revision     string          `json:"revision"`
		Policy       json.RawMessage `json:"policy"`
		PolicyDigest string          `json:"policy_digest"`
		StaticDigest string          `json:"static_digest"`
	} `json:"read_cases"`
	NetworkCases []struct {
		Name         string          `json:"name"`
		Expect       string          `json:"expect"`
		Rule         json.RawMessage `json:"rule"`
		Gateway      json.RawMessage `json:"gateway"`
		SecretCanary string          `json:"secret_canary"`
	} `json:"network_cases"`
}

func loadPolicySafetyVectors(t *testing.T) policySafetyVectors {
	t.Helper()
	raw, err := os.ReadFile("../../../../testdata/openshell-policy-safety.v2.json")
	if err != nil {
		t.Fatal(err)
	}
	var vectors policySafetyVectors
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatal(err)
	}
	if vectors.Schema != "openshell-policy-safety-vectors/v2" {
		t.Fatalf("unexpected vector schema %q", vectors.Schema)
	}
	return vectors
}

func TestSharedPolicySafetyReadVectors(t *testing.T) {
	for _, vector := range loadPolicySafetyVectors(t).ReadCases {
		vector := vector
		t.Run(vector.Name, func(t *testing.T) {
			writes := 0
			client := New(Options{PollInterval: -1, Runner: func(args []string) (int, string, string) {
				if eq(args, "policy", "get", "shared", "--full") {
					return 0, vector.Output, ""
				}
				writes++
				return 1, "", "unexpected"
			}})
			snapshot, err := client.ReadEffective("shared")
			if vector.Expect == "reject" {
				if err == nil {
					t.Fatal("unsafe vector must be rejected")
				}
				if writes != 0 {
					t.Fatal("read rejection must not write")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if snapshot.Revision != vector.Revision || snapshot.PolicyDigest != vector.PolicyDigest || snapshot.StaticDigest != vector.StaticDigest {
				t.Fatalf("snapshot identity mismatch: %+v", snapshot)
			}
			expected, err := canon.Decode(vector.Policy)
			if err != nil {
				t.Fatal(err)
			}
			actualRaw, err := canon.Marshal(snapshot.Policy)
			if err != nil {
				t.Fatal(err)
			}
			expectedRaw, err := canon.Marshal(expected)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(actualRaw, expectedRaw) {
				t.Fatalf("policy mismatch\nactual=%s\nwant=%s", actualRaw, expectedRaw)
			}
		})
	}
}

func TestSharedPolicySafetyNetworkVectors(t *testing.T) {
	for _, vector := range loadPolicySafetyVectors(t).NetworkCases {
		vector := vector
		t.Run(vector.Name, func(t *testing.T) {
			var rule NetworkRule
			decoder := json.NewDecoder(bytes.NewReader(vector.Rule))
			decoder.DisallowUnknownFields()
			decodeErr := decoder.Decode(&rule)
			var gateway map[string]any
			var err error
			if decodeErr == nil {
				gateway, err = networkRulesToGateway([]NetworkRule{rule})
			} else {
				err = decodeErr
			}
			if vector.Expect == "reject" {
				if err == nil {
					t.Fatal("unsupported network rule must be rejected")
				}
				if vector.SecretCanary != "" && strings.Contains(err.Error(), vector.SecretCanary) {
					t.Fatal("network rejection leaked secret canary")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			var expected map[string]any
			dec := json.NewDecoder(bytes.NewReader(vector.Gateway))
			dec.UseNumber()
			if err := dec.Decode(&expected); err != nil {
				t.Fatal(err)
			}
			actualRaw, _ := canon.Marshal(gateway)
			expectedRaw, _ := canon.Marshal(expected)
			if !bytes.Equal(actualRaw, expectedRaw) {
				t.Fatalf("gateway mismatch\nactual=%s\nwant=%s", actualRaw, expectedRaw)
			}
		})
	}
}
