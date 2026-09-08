package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"strings"
	"time"
)

func provenanceError(w http.ResponseWriter, err error) {
	code, status := "provenance_state_unavailable", 500
	var v *provenance.Violation
	if errors.As(err, &v) {
		code, status = v.Code, 400
	}
	if strings.Contains(code, "conflict") {
		status = 409
	}
	if code == "provenance_capacity" {
		status = 503
	}
	writeJSON(w, status, map[string]string{"error": code, "reason_code": code})
}
func readProvenance(w http.ResponseWriter, r *http.Request, out any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		provenanceError(w, &provenance.Violation{Code: "provenance_invalid_request"})
		return false
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		provenanceError(w, &provenance.Violation{Code: "provenance_invalid_request"})
		return false
	}
	return true
}
func (s *Server) provenanceIssuers(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var i provenance.Issuer
	if !readProvenance(w, r, &i) {
		return
	}
	out, err := s.provenance.RegisterIssuer(i)
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 201, out)
}
func (s *Server) provenanceIssuer(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/v1/provenance-issuers/")
	if strings.HasSuffix(path, "/revoke") {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		var body struct{}
		if !readProvenance(w, r, &body) {
			return
		}
		out, err := s.provenance.RevokeIssuer(strings.TrimSuffix(path, "/revoke"), time.Now().UTC())
		if err != nil {
			provenanceError(w, err)
			return
		}
		writeJSON(w, 200, out)
		return
	}
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	out, err := s.provenance.GetIssuer(path)
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 200, out)
}
func (s *Server) provenanceIssue(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var a provenance.Assertion
	if !readProvenance(w, r, &a) {
		return
	}
	out, err := s.provenance.IssueAssertion(a, time.Now().UTC())
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 201, out)
}
func (s *Server) provenanceImport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var a provenance.Assertion
	if !readProvenance(w, r, &a) {
		return
	}
	out, err := s.provenance.ImportAssertion(a, time.Now().UTC())
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 201, out)
}
func (s *Server) provenanceResolve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		ProvenanceID string           `json:"provenance_id"`
		Scope        provenance.Scope `json:"scope"`
	}
	if !readProvenance(w, r, &body) {
		return
	}
	out, err := s.provenance.Resolve(body.ProvenanceID, body.Scope, time.Now().UTC())
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 200, out)
}
