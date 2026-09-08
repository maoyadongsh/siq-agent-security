package effectevidence

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// NetworkOracle is a bounded loopback test server, not a generic network monitor.
// Events are only produced inside its HTTP handler after actual receipt.
type NetworkOracle struct {
	mu                   sync.Mutex
	server               *http.Server
	listener             net.Listener
	host, port, path, id string
	events               []NetworkEvent
}

type NetworkEvent struct {
	Scheme         string `json:"scheme"`
	Host           string `json:"host"`
	Port           string `json:"port"`
	ResolvedTarget string `json:"resolved_target"`
	RequestID      string `json:"request_id"`
	RequestDigest  string `json:"request_digest"`
	ReceivedAt     string `json:"received_at"`
}

func NewNetworkOracle(host string) (*NetworkOracle, error) {
	if host != "127.0.0.1" && host != "localhost" {
		return nil, ErrInvalid
	}
	var nonce [32]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return nil, err
	}
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	_, port, _ := net.SplitHostPort(l.Addr().String())
	o := &NetworkOracle{listener: l, host: host, port: port, path: "/receive/" + hex.EncodeToString(nonce[:16]), id: "oracle-" + hex.EncodeToString(nonce[16:]), events: []NetworkEvent{}}
	o.server = &http.Server{Handler: http.HandlerFunc(o.receive), ReadHeaderTimeout: 2 * time.Second, ReadTimeout: 5 * time.Second, WriteTimeout: 5 * time.Second, IdleTimeout: 5 * time.Second, MaxHeaderBytes: 16 << 10}
	go func() { _ = o.server.Serve(l) }()
	return o, nil
}
func (o *NetworkOracle) URL() string  { return "http://" + net.JoinHostPort(o.host, o.port) + o.path }
func (o *NetworkOracle) Close() error { return o.server.Close() }
func (o *NetworkOracle) Events() []NetworkEvent {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]NetworkEvent{}, o.events...)
}

func (o *NetworkOracle) receive(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != o.path {
		w.WriteHeader(404)
		return
	}
	o.mu.Lock()
	defer o.mu.Unlock()
	if len(o.events) >= 64 {
		w.WriteHeader(503)
		return
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil {
		w.WriteHeader(413)
		return
	}
	bodyHash := sha256.Sum256(body)
	encoded, err := canon.Marshal(map[string]any{"method": r.Method, "uri": r.RequestURI, "body_digest": hex.EncodeToString(bodyHash[:])})
	if err != nil {
		w.WriteHeader(400)
		return
	}
	sum := sha256.Sum256(encoded)
	o.events = append(o.events, NetworkEvent{Scheme: "http", Host: o.host, Port: o.port, ResolvedTarget: o.listener.Addr().String(), RequestID: o.id + "-" + strconv.Itoa(len(o.events)+1), RequestDigest: hex.EncodeToString(sum[:]), ReceivedAt: time.Now().UTC().Format(time.RFC3339Nano)})
	w.WriteHeader(204)
}

// Evidence derives from a retained server event, never from caller-supplied log
// fields. requestedURL comes from the trusted benchmark scenario/action setup.
func (o *NetworkOracle) Evidence(index int, id string, action Action, requestedURL string) (Evidence, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if index < 0 || index >= len(o.events) {
		return Evidence{}, ErrNotFound
	}
	u, err := url.Parse(requestedURL)
	if err != nil || u.User != nil || (u.Scheme != "http" && u.Scheme != "https") {
		return Evidence{}, ErrInvalid
	}
	host, err := runtimeaction.NormalizeHost(u.Hostname())
	if err != nil {
		return Evidence{}, ErrInvalid
	}
	port := u.Port()
	if port == "" {
		port = "80"
		if u.Scheme == "https" {
			port = "443"
		}
	}
	n, err := strconv.Atoi(port)
	if err != nil || n < 1 || n > 65535 {
		return Evidence{}, ErrInvalid
	}
	event := o.events[index]
	result := "expected"
	if event.Scheme != u.Scheme || event.Host != host || event.Port != port {
		result = "unexpected"
	}
	// The event digest binds both the requested endpoint and actual listener log.
	encoded, err := canon.Marshal(map[string]any{"requested_scheme": u.Scheme, "requested_host": host, "requested_port": port, "scheme": event.Scheme, "host": event.Host, "port": event.Port, "resolved_target": event.ResolvedTarget, "request_id": event.RequestID, "request_digest": event.RequestDigest, "received_at": event.ReceivedAt})
	if err != nil {
		return Evidence{}, ErrInvalid
	}
	digest := sha256.Sum256(encoded)
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: event.Host}})
	ref, _ := ResourceReference(refs[0])
	e := Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: id, ActionID: action.ActionID, DecisionReceiptID: action.DecisionReceiptID, EffectType: "network.request", ResourceRef: ref, ExecutionState: "completed", Source: Source{Type: "test_oracle", SourceID: o.id, Independence: "external_independent"}, Coverage: "partial", Result: result, EvidenceDigest: hex.EncodeToString(digest[:]), ObservedAt: event.ReceivedAt, SigningSchema: "local_canonical/v1"}
	return e, e.Validate(time.Now())
}
