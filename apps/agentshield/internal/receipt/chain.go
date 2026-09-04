package receipt

import (
	"bufio"
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
	_ = os.WriteFile(filepath.Join(c.dir, "HEAD"), []byte(fmt.Sprintf("%d %s\n", c.seq, c.head)), 0o600)
	return nil
}

// Head returns the current (seq, hash); seq is -1 for an empty chain.
func (c *Chain) Head() (int, string) { return c.seq, c.head }

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

// Read returns all receipts in chain order.
func (c *Chain) Read() ([]Receipt, error) {
	files, err := c.files()
	if err != nil {
		return nil, err
	}
	var out []Receipt
	for _, p := range files {
		f, err := os.Open(p)
		if err != nil {
			return nil, err
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<20)
		for sc.Scan() {
			var r Receipt
			if err := json.Unmarshal(sc.Bytes(), &r); err != nil {
				_ = f.Close()
				return nil, fmt.Errorf("%s: malformed line: %w", filepath.Base(p), err)
			}
			out = append(out, r)
		}
		_ = f.Close()
		if err := sc.Err(); err != nil {
			return nil, err
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

// Verify recomputes hashes, links and signatures of every receipt in order.
func Verify(receipts []Receipt, pub []byte) error {
	prev := GenesisPrev
	for i, r := range receipts {
		if r.Seq != i {
			return &VerifyError{r.Seq, fmt.Sprintf("seq gap (expected %d)", i)}
		}
		if r.PrevHash != prev {
			return &VerifyError{r.Seq, "prev_hash mismatch"}
		}
		h, err := hashOf(r)
		if err != nil {
			return &VerifyError{r.Seq, "cannot canonicalise"}
		}
		if h != r.Hash {
			return &VerifyError{r.Seq, "hash mismatch (content altered)"}
		}
		if !signing.VerifyBytes(pub, []byte(r.Hash), r.Sig) {
			return &VerifyError{r.Seq, "invalid signature"}
		}
		prev = r.Hash
	}
	return nil
}
