package rawcontent

import "time"

// RuntimeSource is authenticated with the ciphertext. It describes capture
// provenance, not task completion or approval of the captured content.
type RuntimeSource struct {
	RuntimeIdentityRef string `json:"runtime_identity_ref"`
	SessionRef         string `json:"session_ref"`
	BindingRef         string `json:"binding_ref"`
}

func (s RuntimeSource) valid() bool {
	return digestRefPattern.MatchString(s.RuntimeIdentityRef) && digestRefPattern.MatchString(s.SessionRef) && digestRefPattern.MatchString(s.BindingRef)
}

func runtimeSource(identity, session, binding string) (RuntimeSource, bool) {
	i, iok := hashRef(identity)
	s, sok := hashRef(session)
	b, bok := hashRef(binding)
	return RuntimeSource{RuntimeIdentityRef: i, SessionRef: s, BindingRef: b}, iok && sok && bok
}

func validEnvelopeSource(e Envelope) bool {
	return (e.Schema == "local-raw-task-content-envelope/v1" && e.Source == nil) ||
		(e.Schema == "local-raw-task-content-envelope/v2" && e.Source != nil && e.Source.valid())
}

// ListRuntimeOutputs authenticates the entire bounded store before selecting
// exact runtime outputs. Legacy task-only records cannot acquire provenance.
// Metadata may include expired records, but never contains plaintext.
func (s *Store) ListRuntimeOutputs(task, identity, session, binding string, now time.Time) ([]Metadata, error) {
	source, ok := runtimeSource(identity, session, binding)
	if !ok {
		return nil, ErrInvalid
	}
	return s.listMetadataForSource(task, now, &source)
}

// ReadRuntimeOutput checks provenance and expiry again at read time; a listed
// record ID is never authority to retrieve a different session's content.
func (s *Store) ReadRuntimeOutput(task, identity, session, binding, id string, now time.Time) ([]Field, Envelope, error) {
	source, ok := runtimeSource(identity, session, binding)
	if !ok {
		return nil, Envelope{}, ErrInvalid
	}
	return s.readForSource(task, id, now, &source)
}
