package server

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net"
	"path"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

// Only the exact approved control-plane operation can consume the hold.
// No arbitrary command is executed by this route.
func (s *Server) validateOpenShellExecutionBinding(body openshellSessionExecuteRequest) (*grant.Grant, error) {
	if body.Target != body.AgentID || body.Tool != "exec" {
		return nil, fmt.Errorf("openshell_operation_binding_mismatch")
	}
	chain, err := s.d.Chain.Read()
	if err != nil || receipt.Verify(chain, s.d.Key.Public()) != nil {
		return nil, fmt.Errorf("openshell_chain_unverified")
	}
	var decision *receipt.Receipt
	for i := range chain {
		if chain[i].ReceiptID == body.DecisionReceiptID && chain[i].RecordType == "decision" {
			decision = &chain[i]
			break
		}
	}
	if decision == nil || decision.MatchedGrantID == nil {
		return nil, fmt.Errorf("openshell_decision_missing")
	}
	g, err := s.d.Store.GetGrant(*decision.MatchedGrantID)
	if err != nil || g == nil || !grant.Verify(s.d.Key.Public(), *g) || grant.ValidateLifetime(*g, time.Now()) != nil ||
		(g.Status != "deployed" && g.Status != "effective") || g.Platform != body.Platform || g.Subject.ID != body.AgentID {
		return nil, fmt.Errorf("openshell_grant_invalid")
	}
	digest, err := grant.PermissionDigest(*g)
	if err != nil {
		return nil, fmt.Errorf("openshell_grant_invalid")
	}
	fingerprint := s.d.Openshell.InvocationFingerprint()
	if fingerprint == "" {
		return nil, fmt.Errorf("openshell_backend_unbound")
	}
	urls := make([]string, len(body.Endpoints))
	for i, ep := range body.Endpoints {
		urls[i] = "https://" + ep
	}
	expected := map[string]any{"command": "siq-openshell-policy-apply", "authorization_urls": urls, "openshell_policy": map[string]any{
		"target": body.Target, "endpoints": body.Endpoints, "binary_paths": body.BinaryPaths, "expected_revision": body.ExpectedRevision,
		"grant_id": g.GrantID, "grant_digest": digest, "endpoint_fingerprint": fingerprint,
	}}
	a, err := json.Marshal(expected)
	if err != nil {
		return nil, err
	}
	b, err := json.Marshal(body.Params)
	if err != nil || !bytes.Equal(a, b) {
		return nil, fmt.Errorf("openshell_operation_binding_mismatch")
	}
	allowed := grantNetwork(*g)
	for _, ep := range body.Endpoints {
		if !allowed[ep] {
			return nil, fmt.Errorf("endpoint_not_authorized")
		}
	}
	return g, nil
}

func validOpenShellExecutionShape(body openshellSessionExecuteRequest) bool {
	if body.Target == "" || !canonicalRevision(body.ExpectedRevision) || len(body.Endpoints) == 0 || len(body.BinaryPaths) == 0 {
		return false
	}
	for _, p := range body.BinaryPaths {
		if !strings.HasPrefix(p, "/") || path.Clean(p) != p || strings.ContainsFunc(p, func(r rune) bool { return r < 0x20 || r == 0x7f }) {
			return false
		}
	}
	for _, ep := range body.Endpoints {
		host, port, err := net.SplitHostPort(ep)
		n, e := strconv.Atoi(port)
		if err != nil || e != nil || host == "" || n < 1 || n > 65535 || strconv.Itoa(n) != port || strings.ContainsAny(host, "/?#@ \t\r\n") {
			return false
		}
	}
	return true
}
