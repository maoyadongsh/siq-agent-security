package skillimport

import (
	"context"
	"os"
	"path/filepath"
	"regexp"

	"siq-agent-security/apps/agentshield/internal/canon"
)

var digestPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)

type RemoteCreateRequest struct {
	SchemaVersion  string `json:"schema_version"`
	ImportID       string `json:"import_id"`
	URL            string `json:"url"`
	ArchivePath    string `json:"archive_path"`
	ExpectedSHA256 string `json:"expected_sha256"`
	ActorID        string `json:"actor_id"`
}
type RemoteMetadata struct {
	ArchiveSHA256      string `json:"archive_sha256"`
	ArchiveBytes       int64  `json:"archive_bytes"`
	FinalLocatorDigest string `json:"final_locator_digest"`
	ArchivePath        string `json:"archive_path"`
	ExpectedSHA256     string `json:"expected_sha256"`
}

func archivePathValid(value string) bool {
	return value == "" || (validPath(value) && !gitMetadata(value))
}
func remoteValid(r *RemoteMetadata) bool {
	return r != nil && digestPattern.MatchString(r.ArchiveSHA256) && digestPattern.MatchString(r.FinalLocatorDigest) && r.ArchiveBytes > 0 && r.ArchiveBytes <= maxArchiveBytes && archivePathValid(r.ArchivePath) && (r.ExpectedSHA256 == "" || r.ExpectedSHA256 == r.ArchiveSHA256)
}
func recordVersionValid(r Record) bool {
	return (r.SchemaVersion == "local-skill-import/v1" && kindValid(r.SourceKind) && r.Remote == nil) ||
		(r.SchemaVersion == "local-skill-import/v2" && r.SourceKind == "https_zip" && remoteValid(r.Remote))
}
func (s *Store) CreateRemote(ctx context.Context, req RemoteCreateRequest) (*Record, *Analysis, bool, error) {
	if req.SchemaVersion != "local-skill-import-remote-create/v1" || !importID.MatchString(req.ImportID) || !actorValid(req.ActorID) || !archivePathValid(req.ArchivePath) || (req.ExpectedSHA256 != "" && !digestPattern.MatchString(req.ExpectedSHA256)) {
		return nil, nil, false, ErrInvalid
	}
	parsed, err := downloadURL(req.URL)
	if err != nil {
		return nil, nil, false, err
	}
	canonical, err := canon.Marshal(map[string]any{"url": parsed.String(), "archive_path": req.ArchivePath, "expected_sha256": req.ExpectedSHA256})
	if err != nil {
		return nil, nil, false, ErrInvalid
	}
	local := CreateRequest{ImportID: req.ImportID, SourceKind: "https_zip", ActorID: req.ActorID}
	return s.create(ctx, local, parsed.String(), sum(canonical), &req)
}
func (s *Store) remoteTree(ctx context.Context, source, blob, payload string, req *RemoteCreateRequest) (tree, bool, *RemoteMetadata, error) {
	none := emptyTree()
	fetch := s.download
	if fetch == nil {
		fetch = fetchHTTPS
	}
	archive, err := fetch(ctx, source)
	if err != nil {
		return none, false, nil, err
	}
	if int64(len(archive.raw)) > maxArchiveBytes {
		return none, false, nil, ErrLimit
	}
	digest := sum(archive.raw)
	if req.ExpectedSHA256 != "" && req.ExpectedSHA256 != digest {
		return none, false, nil, ErrArchiveMismatch
	}
	final, err := downloadURL(archive.finalURL)
	if err != nil {
		return none, false, nil, err
	}
	metadata := &RemoteMetadata{digest, int64(len(archive.raw)), sum([]byte(final.String())), req.ArchivePath, req.ExpectedSHA256}
	if !remoteValid(metadata) {
		return none, false, nil, ErrInvalid
	}
	target := payload
	if req.ArchivePath != "" {
		target = filepath.Join(blob, "unpacked")
		if err = os.Mkdir(target, 0700); err != nil {
			return none, false, nil, ErrUnavailable
		}
		defer os.RemoveAll(target)
	}
	tree, excluded, err := extractZip(ctx, archive.raw, target)
	if err != nil {
		return none, false, nil, err
	}
	if req.ArchivePath != "" {
		tree, _, err = directoryTree(ctx, filepath.Join(target, filepath.FromSlash(req.ArchivePath)), payload, true)
	}
	return tree, excluded, metadata, err
}
