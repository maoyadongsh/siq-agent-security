package receipt

import (
	"bufio"
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

// GenesisPrev is prev_hash of seq 0.
const GenesisPrev = "0000000000000000000000000000000000000000000000000000000000000000"

// Chain is an append-only, hash-linked receipt log:
//
//	<dir>/<chain_id>/<YYYY-MM-DD>.jsonl   one receipt per line
//	<dir>/<chain_id>/HEAD                 "<seq> <hash>" (acceleration only)
//
// hash = sha256(canon(receipt without hash/sig)); sig = Ed25519(hash hex bytes).
type Chain struct {
	dir     string
	chainID string
	key     *signing.Key
	seq     int
	head    string
	now     func() time.Time
	cpStore *CheckpointStore // optional managed tip (DEV15-E); never receipts/<id>/HEAD
}

// OpenChain opens or creates the chain, recovering (seq, head) from the last
// line on disk (HEAD is only a hint and is re-derived).
func OpenChain(stateDir, chainID string, key *signing.Key) (*Chain, error) {
	if key == nil {
		return nil, errors.New("receipt: signing key required")
	}
	dir := filepath.Join(stateDir, "receipts", chainID)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	c := &Chain{dir: dir, chainID: chainID, key: key, seq: -1, head: GenesisPrev, now: func() time.Time { return time.Now().UTC() }}
	last, err := c.lastReceipt()
	if err != nil {
		return nil, err
	}
	if last != nil {
		c.seq = last.Seq
		c.head = last.Hash
	}
	return c, nil
}

// Append finalises r (seq, prev_hash, hash, sig) and persists it.
func (c *Chain) Append(r *Receipt) error {
	r.ChainID = c.chainID
	r.Seq = c.seq + 1
	r.PrevHash = c.head
	if r.Seq == 0 {
		r.PrevHash = GenesisPrev
	}
	h, err := hashOf(*r)
	if err != nil {
		return err
	}
	r.Hash = h
	r.Sig = c.key.SignBytes([]byte(h))
	line, err := json.Marshal(r)
	if err != nil {
		return err
	}
	day := c.now().Format("2006-01-02")
	f, err := os.OpenFile(filepath.Join(c.dir, day+".jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	if _, err := f.Write(append(line, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	c.seq = r.Seq
	c.head = r.Hash
	headPath := filepath.Join(c.dir, "HEAD")
	tmp, err := os.CreateTemp(c.dir, ".head-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := fmt.Fprintf(tmp, "%d %s\n", c.seq, c.head); err != nil {
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
	if err := os.Rename(tmpName, headPath); err != nil {
		_ = os.Remove(tmpName)
		return err
	}
	if c.cpStore != nil {
		if err := c.cpStore.Publish(c.chainID, c.seq, c.head); err != nil {
			return fmt.Errorf("receipt: append ok but checkpoint publish failed: %w", err)
		}
	}
	return nil
}

// Head returns the current (seq, hash); seq is -1 for an empty chain.
func (c *Chain) Head() (int, string) { return c.seq, c.head }

// ChainID returns the chain identifier.
func (c *Chain) ChainID() string { return c.chainID }

func hashOf(r Receipt) (string, error) {
	r.Hash = ""
	r.Sig = ""
	raw, err := json.Marshal(r)
	if err != nil {
		return "", err
	}
	v, err := canon.Decode(raw)
	if err != nil {
		return "", err
	}
	m := v.(map[string]any)
	delete(m, "hash")
	delete(m, "sig")
	b, err := canon.Marshal(m)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

// ContentHash returns sha256 hex of local_canonical bytes over the receipt
// with hash/sig stripped (DEV09-D). The Ed25519 signature is over this hex
// string's ASCII bytes (signing.SignBytes), not over the canonical document.
func ContentHash(r Receipt) (string, error) {
	return hashOf(r)
}

// VerifyHashSignature checks sigHex is Ed25519 over contentHashHex ASCII bytes.
func VerifyHashSignature(pub ed25519.PublicKey, contentHashHex, sigHex string) bool {
	return signing.VerifyBytes(pub, []byte(contentHashHex), sigHex)
}

func (c *Chain) files() ([]string, error) {
	entries, err := os.ReadDir(c.dir)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), ".jsonl") {
			out = append(out, filepath.Join(c.dir, e.Name()))
		}
	}
	sort.Strings(out)
	return out, nil
}

// Read returns all receipts in chain order. A trailing incomplete line on the
// newest file (crash mid-append) is skipped; a malformed mid-file line fails.
func (c *Chain) Read() ([]Receipt, error) {
	files, err := c.files()
	if err != nil {
		return nil, err
	}
	var out []Receipt
	for fi, p := range files {
		lastFile := fi == len(files)-1
		f, err := os.Open(p)
		if err != nil {
			return nil, err
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<20)
		var lines [][]byte
		for sc.Scan() {
			raw := append([]byte(nil), sc.Bytes()...)
			if len(bytes.TrimSpace(raw)) == 0 {
				continue
			}
			lines = append(lines, raw)
		}
		scanErr := sc.Err()
		_ = f.Close()
		if scanErr != nil {
			return nil, scanErr
		}
		for li, raw := range lines {
			var r Receipt
			if err := json.Unmarshal(raw, &r); err != nil {
				if lastFile && li == len(lines)-1 {
					continue
				}
				return nil, fmt.Errorf("%s: malformed line: %w", filepath.Base(p), err)
			}
			out = append(out, r)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Seq < out[j].Seq })
	return out, nil
}

func (c *Chain) lastReceipt() (*Receipt, error) {
	all, err := c.Read()
	if err != nil {
		return nil, err
	}
	if len(all) == 0 {
		return nil, nil
	}
	return &all[len(all)-1], nil
}

// VerifyError reports the first broken link.
type VerifyError struct {
	Seq    int
	Reason string
}

func (e *VerifyError) Error() string {
	return fmt.Sprintf("receipt chain broken at seq %d: %s", e.Seq, e.Reason)
}

// History integrity labels (DEV15-A / M-G2).
const (
	HistoryVerified = "verified"
	HistoryUnknown  = "unknown"
	HistoryFailed   = "failed"
)

// Checkpoint is an independent tip attestation (max seq + tip hash).
// Files colocated with the receipt chain MUST NOT be treated as a Checkpoint:
// they roll back with the directory and cannot prove truncated-tail detection.
type Checkpoint struct {
	MaxSeq  int
	TipHash string
}

// VerificationReport splits proof scope (DEV15-A).
// PrefixValid means the present contiguous records verify (sig/link/hash).
// HistoryIntegrity is "verified" only with a matching independent Checkpoint;
// without one it is "unknown" even when PrefixValid is true (truncation undetectable offline).
type VerificationReport struct {
	PrefixValid          bool   `json:"prefix_valid"`
	HistoryIntegrity     string `json:"history_integrity"` // verified|unknown|failed
	CheckpointConsistent *bool  `json:"checkpoint_consistent,omitempty"`
	EvidenceFreshness    string `json:"evidence_freshness"` // unknown until freshness contract lands
	MaxSeq               int    `json:"max_seq"`
	TipHash              string `json:"tip_hash,omitempty"`
	Error                string `json:"error,omitempty"`
}

// Verify recomputes hashes, links and signatures of every receipt in order.
// It only proves the present prefix; it does NOT prove history completeness.
func Verify(receipts []Receipt, pub []byte) error {
	rep := VerifyDetailed(receipts, pub, nil)
	if !rep.PrefixValid {
		if rep.Error != "" {
			return &VerifyError{Seq: rep.MaxSeq, Reason: rep.Error}
		}
		return &VerifyError{Seq: 0, Reason: "prefix invalid"}
	}
	return nil
}

// VerifyDetailed returns scoped verification. cp may be nil (offline / no anchor).
func VerifyDetailed(receipts []Receipt, pub []byte, cp *Checkpoint) VerificationReport {
	rep := VerificationReport{
		HistoryIntegrity:  HistoryUnknown,
		EvidenceFreshness: HistoryUnknown,
		MaxSeq:            -1,
	}
	if len(receipts) == 0 {
		rep.PrefixValid = true
		rep.MaxSeq = -1
		if cp != nil {
			ok := cp.MaxSeq < 0 && cp.TipHash == ""
			rep.CheckpointConsistent = &ok
			if ok {
				rep.HistoryIntegrity = HistoryVerified
			} else {
				rep.HistoryIntegrity = HistoryFailed
				rep.Error = "empty chain does not match checkpoint"
			}
		}
		return rep
	}

	prev := GenesisPrev
	for i, r := range receipts {
		if r.Seq != i {
			rep.PrefixValid = false
			rep.HistoryIntegrity = HistoryFailed
			rep.MaxSeq = r.Seq
			rep.Error = fmt.Sprintf("seq gap (expected %d)", i)
			return rep
		}
		if r.PrevHash != prev {
			rep.PrefixValid = false
			rep.HistoryIntegrity = HistoryFailed
			rep.MaxSeq = r.Seq
			rep.Error = "prev_hash mismatch"
			return rep
		}
		h, err := hashOf(r)
		if err != nil {
			rep.PrefixValid = false
			rep.HistoryIntegrity = HistoryFailed
			rep.MaxSeq = r.Seq
			rep.Error = "cannot canonicalise"
			return rep
		}
		if h != r.Hash {
			rep.PrefixValid = false
			rep.HistoryIntegrity = HistoryFailed
			rep.MaxSeq = r.Seq
			rep.Error = "hash mismatch (content altered)"
			return rep
		}
		if !signing.VerifyBytes(pub, []byte(r.Hash), r.Sig) {
			rep.PrefixValid = false
			rep.HistoryIntegrity = HistoryFailed
			rep.MaxSeq = r.Seq
			rep.Error = "invalid signature"
			return rep
		}
		prev = r.Hash
		rep.MaxSeq = r.Seq
		rep.TipHash = r.Hash
	}
	rep.PrefixValid = true

	if cp == nil {
		// Offline / no independent anchor: truncation of the tip is undetectable.
		rep.HistoryIntegrity = HistoryUnknown
		return rep
	}
	ok := cp.MaxSeq == rep.MaxSeq && cp.TipHash == rep.TipHash
	rep.CheckpointConsistent = &ok
	if ok {
		rep.HistoryIntegrity = HistoryVerified
	} else {
		rep.HistoryIntegrity = HistoryFailed
		rep.Error = "checkpoint mismatch (possible truncation or rollback)"
	}
	return rep
}
