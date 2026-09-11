package skillimport

import "siq-agent-security/apps/agentshield/internal/admission"

// Result describes a candidate, never installation or runtime authority.
type Result struct {
	SchemaVersion string              `json:"schema_version"`
	Import        *Record             `json:"import"`
	Admission     admission.Admission `json:"admission"`
	Reused        bool                `json:"reused"`
	Installed     bool                `json:"installed"`
}

func NewResult(record *Record, analysis *Analysis, reused bool) Result {
	version := "local-skill-import-result/v1"
	if record.SchemaVersion == "local-skill-import/v2" {
		version = "local-skill-import-result/v2"
	}
	return Result{SchemaVersion: version, Import: record, Admission: analysis.Admission, Reused: reused, Installed: false}
}
