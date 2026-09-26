package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"regexp"
	"time"

	"siq-agent-security/edge/agent/canon"
	"siq-agent-security/edge/agent/protocol"
)

var errSkillUpload = errors.New("skill_upload_unconfirmed; preserve and retry the original signed batch")
var skillDigestPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
var skillIdentifierPattern = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$`)

// prepareSkillUpload snapshots the collection once. The task runner must journal
// this exact payload before HTTP; retrying must not re-read changing skill files.
func prepareSkillUpload(taskID string, scope json.RawMessage, collection protocol.SkillCollection, signer *Signer) (json.RawMessage, string, error) {
	v2 := collection.SchemaVersion == "enterprise-skill-collection/v2"
	if signer == nil || !initialTaskID.MatchString(taskID) || (!v2 && collection.SchemaVersion != "enterprise-skill-collection/v1") || collection.Truncated || len(collection.Issues) != 0 || len(collection.Observations) > 200 {
		return nil, "", errSkillUpload
	}
	scopeValue, err := canon.Decode(scope)
	if err != nil {
		return nil, "", errSkillUpload
	}
	scopeObject, ok := scopeValue.(map[string]any)
	if !ok {
		return nil, "", errSkillUpload
	}
	roots, rootsOK := scopeObject["roots"].([]any)
	include, includeOK := scopeObject["include"].([]any)
	if !rootsOK || len(roots) == 0 || len(roots) > 16 || !includeOK || len(include) != 1 || include[0] != "SKILL.md" {
		return nil, "", errSkillUpload
	}
	for _, root := range roots {
		if value, ok := root.(string); !ok || value == "" {
			return nil, "", errSkillUpload
		}
	}
	for key := range scopeObject {
		if key != "roots" && key != "include" {
			return nil, "", errSkillUpload
		}
	}
	scopeBytes, err := CanonicalJSON(scopeValue)
	if err != nil {
		return nil, "", errSkillUpload
	}
	redactor := protocol.NewRedactor()
	seen := map[string]bool{}
	for _, item := range collection.Observations {
		if !v2 && item.AncestorSHA256 != nil {
			return nil, "", errSkillUpload
		}
		if v2 {
			if len(item.AncestorSHA256) == 0 || len(item.AncestorSHA256) > 33 || item.AncestorSHA256[0] != item.LocatorSHA256 {
				return nil, "", errSkillUpload
			}
			ancestors := map[string]bool{}
			for _, ancestor := range item.AncestorSHA256 {
				if !skillDigestPattern.MatchString(ancestor) || ancestors[ancestor] {
					return nil, "", errSkillUpload
				}
				ancestors[ancestor] = true
			}
		}
		if !skillDigestPattern.MatchString(item.LocatorSHA256) || !skillDigestPattern.MatchString(item.ManifestSHA256) || seen[item.LocatorSHA256] || item.ParserVersion != "enterprise-skill-manifest/v1" || len(item.DeclaredTools) > 64 {
			return nil, "", errSkillUpload
		}
		seen[item.LocatorSHA256] = true
		if _, err := time.Parse(time.RFC3339Nano, item.ObservedAt); err != nil {
			return nil, "", errSkillUpload
		}
		switch item.ParseStatus {
		case "parsed":
			if !skillIdentifierPattern.MatchString(item.Name) || redactor.RedactString(item.Name) != item.Name || (!item.AllowedToolsPresent && len(item.DeclaredTools) != 0) {
				return nil, "", errSkillUpload
			}
		case "missing_frontmatter", "unsupported", "invalid_utf8":
			if item.Name != "" || item.AllowedToolsPresent || len(item.DeclaredTools) != 0 {
				return nil, "", errSkillUpload
			}
		default:
			return nil, "", errSkillUpload
		}
		tools := map[string]bool{}
		for _, tool := range item.DeclaredTools {
			if !skillIdentifierPattern.MatchString(tool) || redactor.RedactString(tool) != tool || tools[tool] {
				return nil, "", errSkillUpload
			}
			tools[tool] = true
		}
	}
	// Clone before normalizing empty arrays; never mutate the caller's evidence.
	observations := append([]protocol.SkillObservation{}, collection.Observations...)
	for i := range observations {
		if observations[i].DeclaredTools == nil {
			observations[i].DeclaredTools = []string{}
		}
	}
	scopeHash := sha256.Sum256(scopeBytes)
	body := map[string]any{"schema_version": "enterprise-skill-upload/v1", "task_id": taskID,
		"scope_digest": hex.EncodeToString(scopeHash[:]), "observations": observations}
	if v2 {
		body["schema_version"] = "enterprise-skill-upload/v2"
	}
	raw, err := json.Marshal(body)
	if err != nil {
		return nil, "", errSkillUpload
	}
	wire, err := canon.Decode(raw)
	if err != nil {
		return nil, "", errSkillUpload
	}
	signed, err := CanonicalJSON(wire)
	if err != nil {
		return nil, "", errSkillUpload
	}
	signature, err := signer.Sign(signed)
	if err != nil {
		return nil, "", errSkillUpload
	}
	body["signature"] = signature
	raw, err = json.Marshal(body)
	if err != nil {
		return nil, "", errSkillUpload
	}
	digest := sha256.Sum256(signed)
	return raw, hex.EncodeToString(digest[:]), nil
}

func (c *Client) UploadSkills(ctx context.Context, body json.RawMessage, digest string) error {
	wire, err := canon.Decode(body)
	if err != nil {
		return errSkillUpload
	}
	object, ok := wire.(map[string]any)
	if !ok {
		return errSkillUpload
	}
	delete(object, "signature")
	signed, err := CanonicalJSON(object)
	if err != nil {
		return errSkillUpload
	}
	expectedDigest := sha256.Sum256(signed)
	if hex.EncodeToString(expectedDigest[:]) != digest {
		return errSkillUpload
	}
	var request struct {
		TaskID       string                      `json:"task_id"`
		Observations []protocol.SkillObservation `json:"observations"`
	}
	if !skillDigestPattern.MatchString(digest) || json.Unmarshal(body, &request) != nil || !initialTaskID.MatchString(request.TaskID) {
		return errSkillUpload
	}
	var out struct {
		Schema       string `json:"schema_version"`
		TaskID       string `json:"task_id"`
		Digest       string `json:"batch_digest"`
		Observations *int   `json:"observations"`
		Idempotent   *bool  `json:"idempotent"`
	}
	// No implicit retry; durable task handling owns retries of this exact body.
	if c.do(ctx, http.MethodPost, "/edge/v1/skill-batches", body, &out, 0) != nil {
		return errSkillUpload
	}
	if out.Schema != "enterprise-skill-upload-result/v1" || out.TaskID != request.TaskID || out.Digest != digest || out.Observations == nil || out.Idempotent == nil {
		return errSkillUpload
	}
	want := len(request.Observations)
	if *out.Idempotent {
		want = 0
	}
	if *out.Observations != want {
		return errSkillUpload
	}
	return nil
}
