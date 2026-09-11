package grant

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/importsource"
)

var ErrImportPreparationRequired = errors.New("grant_import_preparation_required")
var ErrImportInstallationRequired = errors.New("grant_import_installation_required")
var preparationID = regexp.MustCompile(`^ip-[a-f0-9]{32}$`)

func ImportGrantID(adm admission.Admission, opts Options, actor, request string) (string, error) {
	source, err := importsource.Parse(adm)
	if err != nil || opts.Key == nil || !admission.Verify(opts.Key.Public(), adm) || !preparationID.MatchString(request) || actor == "" || strings.TrimSpace(actor) != actor || !utf8.ValidString(actor) || utf8.RuneCountInString(actor) > 128 || strings.IndexFunc(actor, unicode.IsControl) >= 0 {
		return "", ErrImportPreparationRequired
	}
	if !validPlatforms[opts.Platform] || opts.Subject.Type != "agent_instance" || opts.Subject.ID == "" || len(opts.Subject.ID) > 256 {
		return "", ErrImportPreparationRequired
	}
	raw, err := source.Canonical()
	if err != nil {
		return "", err
	}
	value, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	raw, err = canon.Marshal(map[string]any{"source": value, "platform": opts.Platform, "subject": map[string]any{"type": opts.Subject.Type, "id": opts.Subject.ID}, "actor_id": actor, "request_id": request})
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(raw)
	return "grt-si-" + hex.EncodeToString(digest[:]), nil
}

// BuildImported creates only a pending draft. The caller rechecks the source
// and persists the exact derived admission before publishing the audited grant.
func BuildImported(adm admission.Admission, opts Options, actor, request string) (*Result, error) {
	id, err := ImportGrantID(adm, opts, actor, request)
	if err != nil {
		return nil, err
	}
	opts.importGrantID = id
	return buildGrant(adm, opts)
}
