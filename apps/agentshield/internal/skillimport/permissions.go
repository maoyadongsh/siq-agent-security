package skillimport

import (
	"bytes"
	"context"
	"encoding/json"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

// PermissionAdmission always rechecks the complete immutable candidate. Merely
// knowing an import ID, old content hash, or a signed metadata record is not enough.
func (s *Store) PermissionAdmission(ctx context.Context, id string) (importsource.Source, *admission.Result, error) {
	var source importsource.Source
	record, analysis, err := s.Load(ctx, id)
	if err != nil {
		return source, nil, err
	}
	source = importsource.Source{SchemaVersion: "local-skill-import-permission-source/v1", ImportID: id, ArtifactDigest: record.ArtifactDigest, AnalysisSHA256: record.AnalysisSHA256}
	bound, err := source.Bind(analysis.Admission, s.key)
	if err != nil {
		return source, nil, err
	}
	evidence := make([]admission.Evidence, 0, len(analysis.Evidence))
	for _, original := range analysis.Evidence {
		ev, err := importsource.BindEvidence(original, bound, s.key)
		if err != nil {
			return source, nil, err
		}
		evidence = append(evidence, ev)
	}
	return source, &admission.Result{Admission: bound, Evidence: evidence, SkillCard: analysis.SkillCard}, nil
}
func (s *Store) ValidatePermissionAdmission(ctx context.Context, a admission.Admission) error {
	source, err := importsource.Parse(a)
	if err != nil {
		return err
	}
	expected, result, err := s.PermissionAdmission(ctx, source.ImportID)
	if err != nil {
		return err
	}
	if source != expected {
		return ErrChanged
	}
	actualRaw, e1 := json.Marshal(a)
	expectedRaw, e2 := json.Marshal(result.Admission)
	if e1 != nil || e2 != nil || !bytes.Equal(actualRaw, expectedRaw) {
		return ErrChanged
	}
	return nil
}
