package receipt

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// ReadLimit bounds disk scanning for export / large chains (DEV16-C).
// Zero fields use defaults. This is a disk read budget — not a post-hoc slice
// of an already fully loaded []Receipt.
type ReadLimit struct {
	MaxRecords int   // default 100_000; hard ceiling 1_000_000
	MaxBytes   int64 // raw line bytes scanned; default 64<<20
}

// ReadResult is a budgeted chain scan.
type ReadResult struct {
	Receipts     []Receipt
	BytesScanned int64
	Truncated    bool // stopped early due to MaxRecords or MaxBytes
	DiskBudget   bool // MaxBytes caused the stop
}

const (
	defaultReadMaxRecords = 100_000
	defaultReadMaxBytes   = 64 << 20
	hardReadMaxRecords    = 1_000_000
	hardReadMaxBytes      = 1 << 30
)

func normalizeReadLimit(lim ReadLimit) ReadLimit {
	if lim.MaxRecords <= 0 {
		lim.MaxRecords = defaultReadMaxRecords
	}
	if lim.MaxRecords > hardReadMaxRecords {
		lim.MaxRecords = hardReadMaxRecords
	}
	if lim.MaxBytes <= 0 {
		lim.MaxBytes = defaultReadMaxBytes
	}
	if lim.MaxBytes > hardReadMaxBytes {
		lim.MaxBytes = hardReadMaxBytes
	}
	return lim
}

// ReadLimited streams day files in order and stops when the budget is hit.
// Unlike slicing after Read(), unread file content is not loaded into memory.
func (c *Chain) ReadLimited(lim ReadLimit) (ReadResult, error) {
	lim = normalizeReadLimit(lim)
	files, err := c.files()
	if err != nil {
		return ReadResult{}, err
	}
	out := make([]Receipt, 0, 64)
	var scanned int64
	truncated := false
	diskHit := false

	for fi, p := range files {
		if truncated {
			break
		}
		lastFile := fi == len(files)-1
		f, err := os.Open(p)
		if err != nil {
			return ReadResult{}, err
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<20)
		var pendingErr error
		for sc.Scan() {
			raw := append([]byte(nil), sc.Bytes()...)
			n := int64(len(raw)) + 1
			if scanned+n > lim.MaxBytes {
				truncated = true
				diskHit = true
				break
			}
			scanned += n
			if len(bytes.TrimSpace(raw)) == 0 {
				continue
			}
			if pendingErr != nil {
				_ = f.Close()
				return ReadResult{}, fmt.Errorf("%s: malformed line: %w", filepath.Base(p), pendingErr)
			}
			if len(out) >= lim.MaxRecords {
				truncated = true
				break
			}
			var r Receipt
			if err := json.Unmarshal(raw, &r); err != nil {
				pendingErr = err
				continue
			}
			out = append(out, r)
		}
		scanErr := sc.Err()
		_ = f.Close()
		if scanErr != nil {
			return ReadResult{}, scanErr
		}
		if pendingErr != nil {
			if lastFile {
				// Trailing incomplete line on newest file — skip (same contract as Read).
			} else {
				return ReadResult{}, fmt.Errorf("%s: malformed line: %w", filepath.Base(p), pendingErr)
			}
		}
	}

	sort.SliceStable(out, func(i, j int) bool { return out[i].Seq < out[j].Seq })
	return ReadResult{
		Receipts:     out,
		BytesScanned: scanned,
		Truncated:    truncated,
		DiskBudget:   diskHit,
	}, nil
}
