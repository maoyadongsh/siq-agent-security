package completion

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestNetworkCompletionBindsSignedEndpointAndActualRequest(t *testing.T) {
	oracle, err := effectevidence.NewNetworkOracle("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	defer oracle.Close()
	a := effectevidence.Action{ActionID: "a1", DecisionReceiptID: "r1", TaskID: "t1", IntentID: "i1", IntentDigest: strings.Repeat("a", 64), IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"network.request"}, Resources: runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: "127.0.0.1"}})}
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get(oracle.URL())
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	m, err := oracle.Material(0, oracle.URL())
	if err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	store, err := effectevidence.NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	record, err := store.SubmitNetwork("net-1", m, a, oracle.Source(), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	req := Requirement{RequirementID: "network", EffectType: "network.request", ResourceRef: record.Evidence.ResourceRef, ExpectedDigest: m.Received.RequestDigest, MinimumIndependence: "external_independent", MinimumCoverage: "partial", ExpectedEndpoint: &Endpoint{Scheme: m.Received.Scheme, Host: m.Received.Host, Port: m.Received.Port}}
	check := func(r Requirement, records []effectevidence.Record, want string) {
		t.Helper()
		out, err := Evaluate(Task{ID: a.TaskID, IntentID: a.IntentID, IntentDigest: a.IntentDigest, Requirements: []Requirement{r}}, records, key.Public(), func(string, string) (effectevidence.Action, error) { return a, nil }, time.Now())
		if err != nil || out.Status != want {
			t.Fatal(out, err, want)
		}
	}
	check(req, nil, "incomplete")
	check(req, []effectevidence.Record{record}, "verified")
	bad := req
	bad.ExpectedDigest = strings.Repeat("b", 64)
	check(bad, []effectevidence.Record{record}, "conflicting")
	endpoint := *req.ExpectedEndpoint
	endpoint.Port = "1"
	bad = req
	bad.ExpectedEndpoint = &endpoint
	check(bad, []effectevidence.Record{record}, "conflicting")
	endpoint = *req.ExpectedEndpoint
	endpoint.Scheme = "https"
	bad.ExpectedEndpoint = &endpoint
	check(bad, []effectevidence.Record{record}, "conflicting")
	bad = req
	bad.MinimumCoverage = "full"
	check(bad, []effectevidence.Record{record}, "unknown")
	e := record.Evidence
	e.Signature = ""
	e.EvidenceID = "metadata-only"
	plain, err := store.Submit(e, a, oracle.Source(), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	check(req, []effectevidence.Record{plain}, "unknown")
	encoded, _ := json.Marshal(req)
	var decoded Requirement
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatal(err)
	}
	for _, mutation := range []string{`"port":"0"`, `"port":"65536"`, `"port":"01"`, `"port":null`} {
		raw := strings.Replace(string(encoded), `"port":"`+req.ExpectedEndpoint.Port+`"`, mutation, 1)
		if json.Unmarshal([]byte(raw), &decoded) == nil {
			t.Fatal("invalid endpoint accepted", mutation)
		}
	}
	bad = req
	bad.ExpectedEndpoint = nil
	if bad.Validate() == nil {
		t.Fatal("missing endpoint accepted")
	}
	bad = req
	bad.MinimumIndependence = "host_independent"
	if bad.Validate() == nil {
		t.Fatal("weak independence accepted")
	}
}
