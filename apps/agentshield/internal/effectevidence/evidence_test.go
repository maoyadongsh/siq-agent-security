package effectevidence

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func fixture(t *testing.T) (Evidence, *signing.Key, time.Time) {
	t.Helper()
	raw, err := os.ReadFile("../../testdata/contracts/effect-evidence.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	e, err := Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	return e, key, time.Date(2026, 9, 8, 1, 0, 0, 0, time.UTC)
}

func TestCrossLanguageSignatureAndTampering(t *testing.T) {
	e, key, now := fixture(t)
	if err := e.Verify(key.Public(), now); err != nil {
		t.Fatal(err)
	}
	sig, err := key.SignCanonical(e.Unsigned())
	if err != nil || sig != e.Signature {
		t.Fatal("Python/Go signature mismatch", err)
	}
	for name, edit := range map[string]func(*Evidence){
		"action":       func(e *Evidence) { e.ActionID = "other" },
		"receipt":      func(e *Evidence) { e.DecisionReceiptID = "other" },
		"source":       func(e *Evidence) { e.Source.SourceID = "other" },
		"independence": func(e *Evidence) { e.Source.Independence = "external_independent" },
		"resource":     func(e *Evidence) { e.ResourceRef = "network:sha256:" + string(bytes.Repeat([]byte{'a'}, 64)) },
		"coverage":     func(e *Evidence) { e.Coverage = "full" },
		"result":       func(e *Evidence) { e.Result = "conflicting" },
		"digest":       func(e *Evidence) { e.EvidenceDigest = string(bytes.Repeat([]byte{'b'}, 64)) },
	} {
		t.Run(name, func(t *testing.T) {
			bad := e
			edit(&bad)
			if bad.Verify(key.Public(), now) == nil {
				t.Fatal("tampered record accepted")
			}
		})
	}
}

func TestSelfReportAndInvalidStructure(t *testing.T) {
	e, _, now := fixture(t)
	for _, kind := range []string{"tool_report", "unknown"} {
		good := e
		good.Source.Type = kind
		good.Source.Independence = "self_reported"
		if kind == "unknown" {
			good.Source.Independence = "unknown"
		}
		good.Coverage = "unknown"
		good.Result = "unknown"
		if good.Validate(now) != nil {
			t.Fatal("valid limited report rejected")
		}
		for _, field := range []string{"independence", "coverage", "result"} {
			bad := good
			switch field {
			case "independence":
				bad.Source.Independence = "external_independent"
			case "coverage":
				bad.Coverage = "full"
			case "result":
				bad.Result = "expected"
			}
			if bad.Validate(now) == nil {
				t.Fatal("report elevated", kind, field)
			}
		}
	}
	for _, stamp := range []string{"2026-02-30T01:00:00Z", "2026-09-08T01:00:01Z", "2026-09-08T1:00:00Z", "yesterday"} {
		bad := e
		bad.ObservedAt = stamp
		if bad.Validate(now) == nil {
			t.Fatal("invalid observation time", stamp)
		}
	}
	bad := e
	bad.ResourceRef = "/private/file"
	if bad.Validate(now) == nil {
		t.Fatal("plaintext resource accepted")
	}
	raw, _ := json.Marshal(e)
	for _, invalid := range [][]byte{append(append([]byte{}, raw...), raw...), []byte(`{"source":{"authority":true}}`), bytes.Repeat([]byte{' '}, (64<<10)+1)} {
		if _, err := Decode(invalid); err == nil {
			t.Fatal("invalid wire record accepted")
		}
	}
}

func TestResourceReferenceUsesActionDigest(t *testing.T) {
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "filesystem", Value: "/work/report"}})
	if len(refs) != 1 {
		t.Fatal("missing action reference")
	}
	got, err := ResourceReference(refs[0])
	if err != nil || got != "filesystem:sha256:"+refs[0].Digest {
		t.Fatal(got, err)
	}
	if _, err = ResourceReference(runtimeaction.ResourceRef{Domain: "filesystem", Digest: "/private/file"}); err == nil {
		t.Fatal("invalid resource digest accepted")
	}
}
