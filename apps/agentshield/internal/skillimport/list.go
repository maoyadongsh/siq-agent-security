package skillimport

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type Summary struct {
	CreatedAt      string `json:"created_at"`
	SourceKind     string `json:"source_kind"`
	ActorID        string `json:"actor_id"`
	ArtifactDigest string `json:"artifact_digest"`
	FileCount      int    `json:"file_count"`
	TotalBytes     int64  `json:"total_bytes"`
}
type ListItem struct {
	ImportID      string   `json:"import_id"`
	RecordStatus  string   `json:"record_status"`
	PayloadStatus string   `json:"payload_status"`
	Summary       *Summary `json:"summary"`
}
type Listing struct {
	SchemaVersion string     `json:"schema_version"`
	Items         []ListItem `json:"items"`
}

// List verifies signed metadata only. Every actual use still requires Load.
func (s *Store) List(ctx context.Context) (Listing, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	result := Listing{SchemaVersion: "local-skill-import-list/v1", Items: []ListItem{}}
	if err := ctx.Err(); err != nil {
		return result, err
	}
	dir := filepath.Join(s.dir, "records")
	if err := checkDirs(dir); err != nil {
		return result, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return result, ErrUnavailable
	}
	names, err := f.Readdirnames(129)
	f.Close()
	if err != nil && err != io.EOF {
		return result, ErrUnavailable
	}
	if len(names) > 128 {
		return result, ErrLimit
	}
	for _, name := range names {
		if err := ctx.Err(); err != nil {
			return result, err
		}
		if strings.HasPrefix(name, ".import-") {
			continue
		}
		id := strings.TrimSuffix(name, ".json")
		if name != id+".json" || !importID.MatchString(id) {
			return result, ErrChanged
		}
		if len(result.Items) >= maxImports {
			return result, ErrLimit
		}
		item := ListItem{ImportID: id, RecordStatus: "unavailable", PayloadStatus: "unchecked"}
		rec, err := s.readRecord(ctx, id)
		if err == nil {
			if rec.SchemaVersion == "local-skill-import/v2" {
				result.SchemaVersion = "local-skill-import-list/v2"
			}
			var total int64
			for _, file := range rec.Files {
				total += file.Bytes
			}
			item.RecordStatus = "metadata_verified"
			item.Summary = &Summary{rec.CreatedAt, rec.SourceKind, rec.ActorID, rec.ArtifactDigest, len(rec.Files), total}
		} else if ctx.Err() != nil {
			return result, ctx.Err()
		}
		result.Items = append(result.Items, item)
	}
	sort.Slice(result.Items, func(i, j int) bool {
		a, b := result.Items[i], result.Items[j]
		if (a.Summary == nil) != (b.Summary == nil) {
			return a.Summary != nil
		}
		if a.Summary != nil {
			at, _ := time.Parse(time.RFC3339Nano, a.Summary.CreatedAt)
			bt, _ := time.Parse(time.RFC3339Nano, b.Summary.CreatedAt)
			if !at.Equal(bt) {
				return at.After(bt)
			}
		}
		return a.ImportID < b.ImportID
	})
	return result, nil
}
