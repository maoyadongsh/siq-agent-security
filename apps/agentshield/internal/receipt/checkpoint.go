package receipt

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const (
	// CheckpointFormat is the signed managed checkpoint document.
	CheckpointFormat = "agentshield.checkpoint.v1"
	// CheckpointSubdir is under the state root, sibling of receipts/ — never inside a chain dir.
	CheckpointSubdir = "checkpoints"
)

// ErrCheckpointColocated means the store path is under receipts/ (not independent).
var ErrCheckpointColocated = errors.New("receipt: checkpoint store must not live under receipts/")

// ErrCheckpointMissing means no published checkpoint for the chain.
var ErrCheckpointMissing = errors.New("receipt: managed checkpoint not found")

// ErrCheckpointBadSig means the checkpoint file failed signature verification.
var ErrCheckpointBadSig = errors.New("receipt: managed checkpoint signature invalid")

// ManagedCheckpointDoc is the on-disk signed tip attestation (DEV15-E).
type ManagedCheckpointDoc struct {
	Format        string `json:"format"`
	ChainID       string `json:"chain_id"`
	MaxSeq        int    `json:"max_seq"`
	TipHash       string `json:"tip_hash"`
	IssuedAt      string `json:"issued_at"`
	SigningSchema string `json:"signing_schema"`
	Signature     string `json:"signature"`
	// Note records honesty: same-UID / same-volume rollback of the whole state
	// dir is out of scope; this only resists receipts/-only truncation.
	Note string `json:"note"`
}

const checkpointHonestyNote = "Independent of receipts/<chain>/ (incl. HEAD). Detects chain truncation/rollback relative to this file. Whole state-dir rollback on same trust boundary is not claimed."

// CheckpointStore persists signed tip checkpoints outside the chain directory.
type CheckpointStore struct {
	root string // absolute directory (…/checkpoints)
	key  *signing.Key
	now  func() time.Time
}

// OpenCheckpointStore creates <stateDir>/checkpoints. Rejects roots under receipts/.
func OpenCheckpointStore(stateDir string, key *signing.Key) (*CheckpointStore, error) {
	if stateDir == "" {
		return nil, errors.New("receipt: checkpoint stateDir required")
	}
	if key == nil {
		return nil, errors.New("receipt: checkpoint signing key required")
	}
	abs, err := filepath.Abs(stateDir)
	if err != nil {
		return nil, err
	}
	root := filepath.Join(abs, CheckpointSubdir)
	if err := assertNotUnderReceipts(abs, root); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, err
	}
	return &CheckpointStore{root: root, key: key, now: func() time.Time { return time.Now().UTC() }}, nil
}

// OpenCheckpointStoreAt uses an explicit absolute directory (managed mount).
// The path must not be under any …/receipts/ tree.
func OpenCheckpointStoreAt(dir string, key *signing.Key) (*CheckpointStore, error) {
	if dir == "" || key == nil {
		return nil, errors.New("receipt: checkpoint dir and key required")
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	if err := assertPathNotUnderReceipts(abs); err != nil {
		return nil, err
	}
	if err := os.MkdirAll(abs, 0o700); err != nil {
		return nil, err
	}
	return &CheckpointStore{root: abs, key: key, now: func() time.Time { return time.Now().UTC() }}, nil
}

func assertNotUnderReceipts(stateDir, checkpointRoot string) error {
	receipts := filepath.Join(stateDir, "receipts")
	rel, err := filepath.Rel(receipts, checkpointRoot)
	if err != nil {
		return err
	}
	if rel == "." || !strings.HasPrefix(rel, "..") {
		return fmt.Errorf("%w: %s", ErrCheckpointColocated, checkpointRoot)
	}
	return assertPathNotUnderReceipts(checkpointRoot)
}

func assertPathNotUnderReceipts(abs string) error {
	clean := filepath.Clean(abs)
	base := filepath.Base(clean)
	if base == "receipts" {
		return fmt.Errorf("%w: %s", ErrCheckpointColocated, abs)
	}
	parts := strings.Split(clean, string(os.PathSeparator))
	for i, p := range parts {
		if p == "receipts" && i+1 < len(parts) {
			return fmt.Errorf("%w: %s", ErrCheckpointColocated, abs)
		}
	}
	return nil
}

// Path returns the document path for chainID (never under receipts/).
func (s *CheckpointStore) Path(chainID string) string {
	safe := strings.ReplaceAll(chainID, string(os.PathSeparator), "_")
	safe = strings.ReplaceAll(safe, "..", "_")
	return filepath.Join(s.root, safe+".json")
}

// Publish writes a signed tip checkpoint for the chain (atomic replace).
func (s *CheckpointStore) Publish(chainID string, maxSeq int, tipHash string) error {
	if chainID == "" || tipHash == "" {
		return errors.New("receipt: checkpoint chain_id and tip_hash required")
	}
	if maxSeq < 0 {
		return errors.New("receipt: checkpoint max_seq must be >= 0")
	}
	doc := ManagedCheckpointDoc{
		Format:        CheckpointFormat,
		ChainID:       chainID,
		MaxSeq:        maxSeq,
		TipHash:       tipHash,
		IssuedAt:      s.now().Format(time.RFC3339),
		SigningSchema: signing.SchemaLocalCanonicalV1,
		Note:          checkpointHonestyNote,
	}
	sig, err := signCheckpoint(s.key, doc)
	if err != nil {
		return err
	}
	doc.Signature = sig
	raw, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		return err
	}
	path := s.Path(chainID)
	tmp, err := os.CreateTemp(s.root, ".cp-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(append(raw, '\n')); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
		return err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		_ = os.Remove(tmpName)
		return err
	}
	if err := tmp.Close(); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	return nil
}

// PublishFromChain seals the current chain tip into the store.
func (s *CheckpointStore) PublishFromChain(c *Chain) error {
	if c == nil {
		return errors.New("receipt: nil chain")
	}
	seq, tip := c.Head()
	if seq < 0 || tip == "" || tip == GenesisPrev {
		return errors.New("receipt: empty chain has no tip to checkpoint")
	}
	return s.Publish(c.chainID, seq, tip)
}

// Load verifies the signed document and returns a Checkpoint for VerifyDetailed.
func (s *CheckpointStore) Load(chainID string) (*Checkpoint, error) {
	raw, err := os.ReadFile(s.Path(chainID))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, ErrCheckpointMissing
		}
		return nil, err
	}
	var doc ManagedCheckpointDoc
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("receipt: checkpoint malformed: %w", err)
	}
	if doc.Format != CheckpointFormat {
		return nil, fmt.Errorf("receipt: unknown checkpoint format %q", doc.Format)
	}
	if doc.ChainID != chainID {
		return nil, fmt.Errorf("receipt: checkpoint chain_id mismatch")
	}
	if err := verifyCheckpoint(s.key.Public(), doc); err != nil {
		return nil, err
	}
	return &Checkpoint{MaxSeq: doc.MaxSeq, TipHash: doc.TipHash}, nil
}

// LoadOptional returns (nil, nil) when missing; other errors propagate.
func (s *CheckpointStore) LoadOptional(chainID string) (*Checkpoint, error) {
	cp, err := s.Load(chainID)
	if errors.Is(err, ErrCheckpointMissing) {
		return nil, nil
	}
	return cp, err
}

func signCheckpoint(key *signing.Key, doc ManagedCheckpointDoc) (string, error) {
	doc.Signature = ""
	doc.SigningSchema = signing.SchemaLocalCanonicalV1
	m, err := checkpointMap(doc)
	if err != nil {
		return "", err
	}
	m, err = signing.WithSigningSchema(m, signing.SchemaLocalCanonicalV1)
	if err != nil {
		return "", err
	}
	return key.SignCanonical(m)
}

func verifyCheckpoint(pub []byte, doc ManagedCheckpointDoc) error {
	if doc.Signature == "" {
		return ErrCheckpointBadSig
	}
	sig := doc.Signature
	doc.Signature = ""
	m, err := checkpointMap(doc)
	if err != nil {
		return err
	}
	if err := signing.VerifyDocument(pub, m, sig); err != nil {
		return fmt.Errorf("%w: %v", ErrCheckpointBadSig, err)
	}
	return nil
}

func checkpointMap(doc ManagedCheckpointDoc) (map[string]any, error) {
	raw, err := json.Marshal(doc)
	if err != nil {
		return nil, err
	}
	dec, err := canon.Decode(raw)
	if err != nil {
		return nil, err
	}
	m, ok := dec.(map[string]any)
	if !ok {
		return nil, errors.New("receipt: checkpoint must be object")
	}
	delete(m, "signature")
	return m, nil
}

// AttachCheckpointStore enables auto-publish after successful Append (managed mode).
func (c *Chain) AttachCheckpointStore(s *CheckpointStore) {
	c.cpStore = s
}

// RejectColocatedHEAD documents that receipts/<id>/HEAD is not a Checkpoint.
// Callers must use CheckpointStore.Load, never parse HEAD into VerifyDetailed.
func RejectColocatedHEAD(_ string) (*Checkpoint, error) {
	return nil, errors.New("receipt: colocated HEAD is not an independent checkpoint (DEV15-E)")
}
