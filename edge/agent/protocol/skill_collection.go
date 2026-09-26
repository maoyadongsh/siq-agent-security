package protocol

const OpCollectSkills = "collect_skills"
const OpCollectSkillsV2 = "collect_skills_v2"

type SkillObservation struct {
	AncestorSHA256      []string `json:"ancestor_sha256,omitempty"`
	LocatorSHA256       string   `json:"locator_sha256"`
	ManifestSHA256      string   `json:"manifest_sha256"`
	ParserVersion       string   `json:"parser_version"`
	ParseStatus         string   `json:"parse_status"`
	Name                string   `json:"name,omitempty"`
	AllowedToolsPresent bool     `json:"allowed_tools_present"`
	DeclaredTools       []string `json:"declared_tools"`
	ObservedAt          string   `json:"observed_at"`
}

type SkillCollectionIssue struct {
	LocatorSHA256 string `json:"locator_sha256"`
	Status        string `json:"status"`
}

type SkillCollection struct {
	SchemaVersion string                 `json:"schema_version"`
	Observations  []SkillObservation     `json:"observations"`
	Issues        []SkillCollectionIssue `json:"issues"`
	Truncated     bool                   `json:"truncated"`
}
