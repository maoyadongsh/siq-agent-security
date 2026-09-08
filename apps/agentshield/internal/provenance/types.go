package provenance

type Scope struct {
	Platform  string `json:"platform"`
	SessionID string `json:"session_id"`
	AgentID   string `json:"agent_id"`
	TaskID    string `json:"task_id"`
}
type Source struct {
	Type     string `json:"type"`
	SourceID string `json:"source_id"`
	Trust    string `json:"trust"`
}
type Assertion struct {
	SchemaVersion string   `json:"schema_version"`
	ProvenanceID  string   `json:"provenance_id"`
	Source        Source   `json:"source"`
	Scope         Scope    `json:"scope"`
	ContentDigest string   `json:"content_digest"`
	Parents       []string `json:"parents"`
	Derivation    string   `json:"derivation"`
	IssuedAt      string   `json:"issued_at"`
	ExpiresAt     string   `json:"expires_at"`
	Issuer        string   `json:"issuer"`
	SigningSchema string   `json:"signing_schema"`
	Signature     string   `json:"signature"`
}
type ParameterBinding struct {
	ParameterPath  string   `json:"parameter_path"`
	ProvenanceRefs []string `json:"provenance_refs"`
}
type Constraint struct {
	ParameterPath      string   `json:"parameter_path"`
	AllowedSourceTypes []string `json:"allowed_source_types"`
	MinimumTrust       string   `json:"minimum_trust"`
	Required           bool     `json:"required"`
}
type Issuer struct {
	IssuerID           string   `json:"issuer_id"`
	PublicKey          string   `json:"public_key,omitempty"`
	LocalKeyRef        string   `json:"local_key_ref,omitempty"`
	AllowedSourceTypes []string `json:"allowed_source_types"`
	MaxTrustLevel      string   `json:"max_trust_level"`
	Scope              Scope    `json:"scope"`
	ExpiresAt          string   `json:"expires_at"`
	RevokedAt          string   `json:"revoked_at,omitempty"`
}
type Violation struct{ Code string }

func (v *Violation) Error() string { return v.Code }
func failure(code string) error    { return &Violation{Code: code} }
