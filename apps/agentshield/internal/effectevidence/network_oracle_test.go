package effectevidence

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestNetworkOracleActualReceiptAndRedirect(t *testing.T) {
	oracle, err := NewNetworkOracle("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	defer oracle.Close()
	_, key, _ := fixture(t)
	a := Action{ActionID: "network-action", DecisionReceiptID: "network-receipt", TaskID: "network-task", IssuedAt: time.Now().Add(-time.Minute), Authorized: true, Effects: []string{"network.request"}, Resources: runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: "127.0.0.1"}})}
	if _, err = oracle.Evidence(0, "network-fake", a, oracle.URL()); !errors.Is(err, ErrNotFound) {
		t.Fatal("fake tool success became independent evidence", err)
	}
	client := &http.Client{Timeout: 3 * time.Second, Transport: &http.Transport{Proxy: nil}}
	defer client.CloseIdleConnections()
	req, _ := http.NewRequest("POST", oracle.URL(), strings.NewReader("private fixture content"))
	req.Host = "forged.example"
	response, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 204 {
		t.Fatal(response.StatusCode)
	}
	e, err := oracle.Evidence(0, "network-direct", a, oracle.URL())
	if err != nil || e.Result != "expected" || e.Source.Independence != "external_independent" {
		t.Fatal(e, err)
	}
	s, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	r, err := s.Submit(e, a, e.Source, time.Now())
	if err != nil || r.Evidence.Result != "expected" {
		t.Fatal(r, err)
	}
	material, err := oracle.Material(0, oracle.URL())
	if err != nil {
		t.Fatal(err)
	}
	archived, err := s.SubmitNetwork("network-material", material, a, e.Source, time.Now())
	if err != nil || archived.NetworkObservation == nil {
		t.Fatal(archived, err)
	}
	retry, err := s.SubmitNetwork("network-material", material, a, e.Source, time.Now())
	if err != nil || retry.Signature != archived.Signature {
		t.Fatal("network material retry changed evidence", err)
	}
	read, err := s.Get("network-material", time.Now())
	if err != nil || read.NetworkObservation.Received != material.Received {
		t.Fatal(read, err)
	}
	plain := archived.Evidence
	plain.Signature = ""
	if _, err = s.Submit(plain, a, e.Source, time.Now()); !errors.Is(err, ErrConflict) {
		t.Fatal("network material removed on retry", err)
	}
	read.NetworkObservation.RequestedPort = "1"
	read.Signature, err = key.SignCanonical(read.unsigned())
	if err != nil {
		t.Fatal(err)
	}
	changed, _ := json.Marshal(read)
	if err = os.WriteFile(filepath.Join(s.dir, "network-material.json"), changed, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get("network-material", time.Now()); !errors.Is(err, ErrState) {
		t.Fatal("altered network material rebound to old evidence", err)
	}
	logs := oracle.Events()
	raw, _ := json.Marshal(logs)
	if strings.Contains(string(raw), "private fixture") || strings.Contains(string(raw), "forged.example") || strings.Contains(string(raw), "/receive/") {
		t.Fatal("server log leaked request data or trusted Host header")
	}
	logs[0].Host = "forged.example"
	if oracle.Events()[0].Host != "127.0.0.1" {
		t.Fatal("caller mutated server event")
	}
	redirect := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, oracle.URL(), http.StatusFound) }))
	defer redirect.Close()
	approved := strings.Replace(redirect.URL, "127.0.0.1", "localhost", 1)
	response, err = client.Get(approved)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	a.Resources = runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: "localhost"}})
	e, err = oracle.Evidence(1, "network-redirect", a, approved)
	if err != nil || e.Result != "unexpected" {
		t.Fatal("redirect target hidden", e, err)
	}
	r, err = s.Submit(e, a, e.Source, time.Now())
	if err != nil || r.FindingCode != "effect_scope_mismatch" {
		t.Fatal(r, err)
	}
	a.Authorized = false
	e.EvidenceID = "network-denied"
	r, err = s.Submit(e, a, e.Source, time.Now())
	if err != nil || r.FindingCode != "unauthorized_effect_observed" {
		t.Fatal(r, err)
	}
}

func TestNetworkOracleRequestAndEventBudgets(t *testing.T) {
	if _, err := NewNetworkOracle("0.0.0.0"); err == nil {
		t.Fatal("public listener allowed")
	}
	o, err := NewNetworkOracle("127.0.0.1")
	if err != nil {
		t.Fatal(err)
	}
	defer o.Close()
	client := &http.Client{Timeout: 3 * time.Second, Transport: &http.Transport{Proxy: nil}}
	defer client.CloseIdleConnections()
	r, err := client.Post(o.URL(), "text/plain", strings.NewReader(strings.Repeat("x", (1<<20)+1)))
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 413 || len(o.Events()) != 0 {
		t.Fatal("oversize receipt became complete event")
	}
	for i := 0; i < 65; i++ {
		r, err = client.Get(o.URL())
		if err != nil {
			t.Fatal(err)
		}
		r.Body.Close()
		want := 204
		if i == 64 {
			want = 503
		}
		if r.StatusCode != want {
			t.Fatal(i, r.StatusCode)
		}
	}
	if len(o.Events()) != 64 {
		t.Fatal("event capacity exceeded")
	}
}
