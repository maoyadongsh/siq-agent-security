package effectevidence

import (
	"crypto/sha256"
	"encoding/hex"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

type NetworkObservation struct {
	RequestedScheme string       `json:"requested_scheme"`
	RequestedHost   string       `json:"requested_host"`
	RequestedPort   string       `json:"requested_port"`
	Received        NetworkEvent `json:"received"`
}

func networkMaterial(event NetworkEvent, requestedURL string) (NetworkObservation, error) {
	u, err := url.Parse(requestedURL)
	if err != nil || u.User != nil {
		return NetworkObservation{}, ErrInvalid
	}
	host, err := runtimeaction.NormalizeHost(u.Hostname())
	if err != nil {
		return NetworkObservation{}, ErrInvalid
	}
	port := u.Port()
	if port == "" {
		port = "80"
		if u.Scheme == "https" {
			port = "443"
		}
	}
	m := NetworkObservation{RequestedScheme: u.Scheme, RequestedHost: host, RequestedPort: port, Received: event}
	return m, m.validate()
}
func validPort(p string) bool {
	n, err := strconv.Atoi(p)
	return err == nil && n > 0 && n <= 65535 && strconv.Itoa(n) == p
}
func (m NetworkObservation) validate() error {
	host, err := runtimeaction.NormalizeHost(m.RequestedHost)
	if err != nil || host != m.RequestedHost || !member(m.RequestedScheme, "http", "https") || !validPort(m.RequestedPort) {
		return ErrInvalid
	}
	e := m.Received
	ip, port, err := net.SplitHostPort(e.ResolvedTarget)
	if err != nil || ip != "127.0.0.1" || port != e.Port || !validPort(e.Port) || e.Scheme != "http" || !member(e.Host, "localhost", "127.0.0.1") || !idPattern.MatchString(e.RequestID) || !digestPattern.MatchString(e.RequestDigest) || len(e.ReceivedAt) > 64 || !timePattern.MatchString(e.ReceivedAt) {
		return ErrInvalid
	}
	if _, err = time.Parse(time.RFC3339Nano, e.ReceivedAt); err != nil {
		return ErrInvalid
	}
	return nil
}
func (m NetworkObservation) evidenceAt(id string, action Action, source Source, now time.Time) (Evidence, error) {
	index := strings.LastIndex(m.Received.RequestID, "-")
	identityMatches := index > 0 && m.Received.RequestID[:index] == source.SourceID
	if m.validate() != nil || source.Type != "test_oracle" || source.Independence != "external_independent" || !identityMatches {
		return Evidence{}, ErrInvalid
	}
	event := m.Received
	result := "expected"
	if event.Scheme != m.RequestedScheme || event.Host != m.RequestedHost || event.Port != m.RequestedPort {
		result = "unexpected"
	}
	encoded, err := canon.Marshal(map[string]any{"requested_scheme": m.RequestedScheme, "requested_host": m.RequestedHost, "requested_port": m.RequestedPort, "scheme": event.Scheme, "host": event.Host, "port": event.Port, "resolved_target": event.ResolvedTarget, "request_id": event.RequestID, "request_digest": event.RequestDigest, "received_at": event.ReceivedAt})
	if err != nil {
		return Evidence{}, ErrInvalid
	}
	sum := sha256.Sum256(encoded)
	refs := runtimeaction.ResourceRefs([]runtimeaction.Resource{{Domain: "network", Value: event.Host}})
	ref, _ := ResourceReference(refs[0])
	e := Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: id, ActionID: action.ActionID, DecisionReceiptID: action.DecisionReceiptID, EffectType: "network.request", ResourceRef: ref, ExecutionState: "completed", Source: source, Coverage: "partial", Result: result, EvidenceDigest: hex.EncodeToString(sum[:]), ObservedAt: event.ReceivedAt, SigningSchema: "local_canonical/v1"}
	return e, e.Validate(now)
}
func networkMaterialMatches(m NetworkObservation, e Evidence, now time.Time) bool {
	derived, err := m.evidenceAt(e.EvidenceID, Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID}, e.Source, now)
	return err == nil && derived.EvidenceDigest == e.EvidenceDigest && derived.ResourceRef == e.ResourceRef && derived.ObservedAt == e.ObservedAt && derived.ExecutionState == e.ExecutionState && derived.EffectType == e.EffectType && derived.Coverage == e.Coverage
}
