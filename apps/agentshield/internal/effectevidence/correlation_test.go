package effectevidence

import (
	"errors"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestCorrelationRejectsForgedAuthorityAndClassifiesIncidents(t *testing.T) {
	e, _, now := fixture(t)
	a := Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID, IssuedAt: now, Authorized: true, Effects: []string{e.EffectType}, Resources: []runtimeaction.ResourceRef{{Domain: "filesystem", Digest: strings.Repeat("b", 64)}}}
	got, code, err := Correlate(e, a, e.Source, now)
	if err != nil || code != "" || got.Result != "expected" || got.Signature != "" {
		t.Fatal(got, code, err)
	}
	for _, which := range []string{"action", "receipt", "source", "type", "independence", "time"} {
		bad := e
		switch which {
		case "action":
			bad.ActionID = "forged"
		case "receipt":
			bad.DecisionReceiptID = "forged"
		case "source":
			bad.Source.SourceID = "forged"
		case "type":
			bad.Source.Type = "test_oracle"
		case "independence":
			bad.Source.Independence = "external_independent"
		case "time":
			bad.ObservedAt = now.Add(-time.Second).Format(time.RFC3339)
		}
		if _, _, err := Correlate(bad, a, e.Source, now); err == nil {
			t.Fatal("forged context accepted", which)
		}
	}
	a.Authorized = false
	got, code, err = Correlate(e, a, e.Source, now)
	if err != nil || got.Result != "unexpected" || code != "unauthorized_effect_observed" {
		t.Fatal(got, code, err)
	}
	a.Authorized = true
	for _, which := range []string{"effect", "resource"} {
		bad := e
		if which == "effect" {
			bad.EffectType = "network.send"
		} else {
			bad.ResourceRef = "network:sha256:" + strings.Repeat("a", 64)
		}
		got, code, err = Correlate(bad, a, e.Source, now)
		if err != nil || got.Result != "unexpected" || code != "effect_scope_mismatch" {
			t.Fatal(got, code, err)
		}
	}
	if _, _, err = Correlate(e, Action{}, e.Source, now); !errors.Is(err, ErrCorrelation) {
		t.Fatal(err)
	}
}

func TestSelfReportDoesNotCreateIndependentIncident(t *testing.T) {
	e, _, now := fixture(t)
	e.Source = Source{Type: "tool_report", SourceID: "adapter", Independence: "self_reported"}
	e.Coverage = "unknown"
	e.Result = "unknown"
	a := Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID, IssuedAt: now, Authorized: false}
	got, code, err := Correlate(e, a, e.Source, now)
	if err != nil || code != "" || got.Result != "unknown" {
		t.Fatal(got, code, err)
	}
}
