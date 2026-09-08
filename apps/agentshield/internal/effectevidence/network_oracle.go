package effectevidence

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net"
	"net/http"
	"strconv"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
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
	m, err := o.Material(index, requestedURL)
	if err != nil {
		return Evidence{}, err
	}
	return m.evidenceAt(id, action, Source{Type: "test_oracle", SourceID: o.id, Independence: "external_independent"}, time.Now())
}
func (o *NetworkOracle) Material(index int, requestedURL string) (NetworkObservation, error) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if index < 0 || index >= len(o.events) {
		return NetworkObservation{}, ErrNotFound
	}
	return networkMaterial(o.events[index], requestedURL)
}
