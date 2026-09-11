package skillinstall

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

const maxInspectionEntries = 8192
const maxInspectionChanges = 200

type Record struct {
	SchemaVersion  string     `json:"schema_version"`
	InstallID      string     `json:"install_id"`
	Plan           Plan       `json:"plan"`
	ClaimSignature string     `json:"claim_signature"`
	RecordedStatus string     `json:"recorded_status"`
	Operation      *Operation `json:"operation"`
}
type CatalogIssue struct {
	InstallID *string `json:"install_id"`
	Code      string  `json:"code"`
}
type Catalog struct {
	SchemaVersion   string         `json:"schema_version"`
	CheckedAt       string         `json:"checked_at"`
	PlatformChanges bool           `json:"platform_changes"`
	Items           []Record       `json:"items"`
	Issues          []CatalogIssue `json:"issues"`
}
type ContentChange struct {
	PathDisplay string `json:"path_display"`
	PathDigest  string `json:"path_digest"`
	Kind        string `json:"kind"`
	Change      string `json:"change"`
}
type Inspection struct {
	SchemaVersion      string          `json:"schema_version"`
	Record             Record          `json:"record"`
	CheckedAt          string          `json:"checked_at"`
	PlatformChanges    bool            `json:"platform_changes"`
	TargetState        string          `json:"target_state"`
	ComparisonComplete bool            `json:"comparison_complete"`
	Changes            []ContentChange `json:"changes"`
	ChangesTotal       int             `json:"changes_total"`
	ChangesTruncated   bool            `json:"changes_truncated"`
	IssueCode          *string         `json:"issue_code"`
}

func (s *Store) historicalRecord(ctx context.Context, id string) (*Record, *Claim, error) {
	c, err := s.claim(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	op, err := s.readOutcome(ctx, c)
	if err != nil && !errors.Is(err, ErrRecoveryRequired) {
		return nil, nil, err
	}
	status := "recovery_required"
	if op != nil {
		status = op.Status
	}
	return &Record{"local-skill-install-record/v1", id, c.Plan, c.Signature, status, op}, c, nil
}

// Catalog reads signed metadata only. Current target and permission validity
// must not be inferred from an installed historical outcome.
func (s *Store) Catalog(ctx context.Context) (*Catalog, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	dir := filepath.Join(s.dir, "operations")
	if err := checkDirectories(dir); err != nil {
		return nil, err
	}
	f, err := os.Open(dir)
	if err != nil {
		return nil, ErrUnavailable
	}
	names, err := f.Readdirnames(257)
	f.Close()
	if err != nil && err != io.EOF {
		return nil, ErrUnavailable
	}
	if len(names) > 256 {
		return nil, ErrLimit
	}
	sort.Strings(names)
	out := &Catalog{SchemaVersion: "local-skill-install-catalog/v1", CheckedAt: s.now().UTC().Format(time.RFC3339Nano), Items: []Record{}, Issues: []CatalogIssue{}}
	ids := map[string]bool{}
	for _, name := range names {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		suffix := ""
		for _, candidate := range []string{".claim.json", ".result.json", ".recovered.json"} {
			if strings.HasSuffix(name, candidate) {
				suffix = candidate
				break
			}
		}
		if suffix == "" {
			continue
		}
		id := strings.TrimSuffix(name, suffix)
		if !validInstallID(id) {
			out.Issues = append(out.Issues, CatalogIssue{nil, "record_unavailable"})
			continue
		}
		ids[id] = true
	}
	if len(ids) > 64 {
		return nil, ErrLimit
	}
	ordered := make([]string, 0, len(ids))
	for id := range ids {
		ordered = append(ordered, id)
	}
	sort.Strings(ordered)
	for _, id := range ordered {
		record, _, err := s.historicalRecord(ctx, id)
		if err != nil {
			if ctx.Err() != nil {
				return nil, ctx.Err()
			}
			out.Issues = append(out.Issues, CatalogIssue{&id, "record_unavailable"})
			continue
		}
		out.Items = append(out.Items, *record)
	}
	return out, nil
}

func (r *Inspection) add(path, kind, change string) {
	r.ChangesTotal++
	if len(r.Changes) >= maxInspectionChanges {
		r.ChangesTruncated = true
		return
	}
	display := path
	if display == "" {
		display = "."
	}
	// Unknown user names can contain controls or invalid UTF-8. The display is
	// escaped and bounded; the digest distinguishes even truncated names.
	display = strconv.QuoteToGraphic(display)
	display = display[1 : len(display)-1]
	runes := []rune(display)
	if len(runes) > 1024 {
		display = string(runes[:1023]) + "…"
	}
	r.Changes = append(r.Changes, ContentChange{display, hash([]byte(path)), kind, change})
}

func (s *Store) Inspect(ctx context.Context, id string) (*Inspection, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	select {
	case stageSlot <- struct{}{}:
		defer func() { <-stageSlot }()
	case <-ctx.Done():
		return nil, ctx.Err()
	}
	record, c, err := s.historicalRecord(ctx, id)
	if err != nil {
		return nil, err
	}
	out := &Inspection{SchemaVersion: "local-skill-install-inspection/v1", Record: *record, TargetState: "unavailable", Changes: []ContentChange{}}
	err = s.compareTarget(ctx, c, out)
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	out.CheckedAt = s.now().UTC().Format(time.RFC3339Nano)
	if err != nil {
		code := "target_unavailable"
		if errors.Is(err, ErrLimit) {
			code = "comparison_budget_exceeded"
		}
		out.IssueCode = &code
		out.TargetState = "unavailable"
		return out, nil
	}
	out.ComparisonComplete = true
	if out.TargetState != "missing" {
		out.TargetState = "matched"
		if out.ChangesTotal > 0 {
			out.TargetState = "changed"
		}
	}
	return out, nil
}

type inspectionChild struct {
	path                string
	fileIndex, dirIndex int
}

func (s *Store) compareTarget(ctx context.Context, c *Claim, out *Inspection) error {
	destination, pool, err := s.destination(ctx, c.Plan)
	if err != nil {
		return err
	}
	children := map[string][]inspectionChild{}
	dirs := append([]string{""}, c.Directories...)
	parent := func(path string) string {
		p := filepath.ToSlash(filepath.Dir(filepath.FromSlash(path)))
		if p == "." {
			return ""
		}
		return p
	}
	for i, dir := range dirs {
		if i > 0 {
			p := parent(dir)
			children[p] = append(children[p], inspectionChild{dir, -1, i})
		}
	}
	for i, file := range c.Files {
		p := parent(file.Path)
		children[p] = append(children[p], inspectionChild{file.Path, i, -1})
	}
	for path := range children {
		sort.Slice(children[path], func(i, j int) bool { return children[path][i].path < children[path][j].path })
	}
	observed := 0
	var visit func(string, int) error
	visit = func(relative string, index int) error {
		if err := ctx.Err(); err != nil {
			return err
		}
		path := filepath.Join(destination, filepath.FromSlash(relative))
		if err := checkDirectories(filepath.Dir(path)); err != nil {
			return err
		}
		info, err := os.Lstat(path)
		if os.IsNotExist(err) {
			out.add(relative, "directory", "removed")
			if relative == "" {
				out.TargetState = "missing"
			}
			return nil
		}
		if err != nil {
			return ErrUnavailable
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			out.add(relative, "directory", "type_changed")
			return nil
		}
		if err := s.ownerMatches(ctx, c, destination, pool, relative, index); err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			out.add(relative, "directory", "ownership_changed")
		}
		if err := checkDirectories(path); err != nil {
			return err
		}
		f, err := os.Open(path)
		if err != nil {
			return ErrUnavailable
		}
		names, err := f.Readdirnames(maxInspectionEntries - observed + 1)
		f.Close()
		if err != nil && err != io.EOF {
			return ErrUnavailable
		}
		observed += len(names)
		if observed > maxInspectionEntries {
			return ErrLimit
		}
		sort.Strings(names)
		expected := map[string]bool{ownerName: true}
		for _, child := range children[relative] {
			expected[filepath.Base(filepath.FromSlash(child.path))] = true
		}
		for _, name := range names {
			if err := ctx.Err(); err != nil {
				return err
			}
			if expected[name] {
				continue
			}
			// No recursion and no content reads for entries outside the signed manifest.
			unknown := name
			if relative != "" {
				unknown = relative + "/" + name
			}
			item, err := os.Lstat(filepath.Join(path, name))
			if err != nil {
				return ErrUnavailable
			}
			kind := "other"
			if item.IsDir() {
				kind = "directory"
			} else if item.Mode().IsRegular() {
				kind = "file"
			}
			out.add(unknown, kind, "added")
		}
		for _, child := range children[relative] {
			if err := ctx.Err(); err != nil {
				return err
			}
			if child.dirIndex >= 0 {
				if err := visit(child.path, child.dirIndex); err != nil {
					return err
				}
				continue
			}
			file := c.Files[child.fileIndex]
			target := filepath.Join(destination, filepath.FromSlash(file.Path))
			if err := checkDirectories(filepath.Dir(target)); err != nil {
				return err
			}
			info, err := os.Lstat(target)
			if os.IsNotExist(err) {
				out.add(file.Path, "file", "removed")
				continue
			}
			if err != nil {
				return ErrUnavailable
			}
			if !info.Mode().IsRegular() {
				out.add(file.Path, "file", "type_changed")
				continue
			}
			if info.Size() != file.Bytes || (info.Mode().Perm()&0111 != 0) != file.Executable {
				out.add(file.Path, "file", "modified")
				continue
			}
			raw, opened, err := readBounded(ctx, target, 8<<20)
			if err != nil {
				return err
			}
			if int64(len(raw)) != file.Bytes || hash(raw) != file.SHA256 || (opened.Mode().Perm()&0111 != 0) != file.Executable {
				out.add(file.Path, "file", "modified")
				continue
			}
			if checkDirectories(pool) != nil {
				out.add(file.Path, "file", "ownership_changed")
				continue
			}
			owned, err := os.Lstat(opaque(pool, "f", child.fileIndex))
			if err != nil || !owned.Mode().IsRegular() || !os.SameFile(opened, owned) {
				out.add(file.Path, "file", "ownership_changed")
			}
		}
		return nil
	}
	return visit("", 0)
}
