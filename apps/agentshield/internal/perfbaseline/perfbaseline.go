// Package perfbaseline builds measured local-chain performance observations
// for DEV16-D. Numbers are observations only — no prefilled SLA pass/fail.
package perfbaseline

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"sort"
	"time"

	"siq-agent-security/apps/agentshield/internal/export"
	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const Format = "agentshield.perf_baseline.v1"

// HonestyNote is embedded in every report so consumers cannot treat this as SLA.
const HonestyNote = "Observations only. No SLA pass/fail. Do not prefill millisecond guarantees; compare like-for-like hardware/version later."

// Scale names for documented presets (DEV16 plan: 1万/10万).
const (
	ScaleSmoke  = "smoke"  // CI-safe
	ScaleMedium = "medium" // ~10k receipts
	ScaleLarge  = "large"  // ~100k receipts; operator-run
)

// Options configures a single measured run.
type Options struct {
	Scale         string
	Receipts      int // 0 → from Scale
	ReadSamples   int
	ExportSamples int
	StateDir      string // empty → TempDir (caller must not reuse across trust boundaries)
	Seed          []byte
}

// Report is the frozen JSON observation document.
type Report struct {
	Format      string      `json:"format"`
	MeasuredAt  string      `json:"measured_at"`
	Environment Environment `json:"environment"`
	Scale       ScaleInfo   `json:"scale"`
	Metrics     Metrics     `json:"metrics"`
	Notes       string      `json:"notes"`
	// Thresholds is always null/omitted: this harness does not decide pass/fail.
	Thresholds any `json:"thresholds"`
}

// Environment records reproducible machine context (no secrets).
type Environment struct {
	GoVersion    string `json:"go_version"`
	OS           string `json:"os"`
	Arch         string `json:"arch"`
	NumCPU       int    `json:"num_cpu"`
	HostnameHash string `json:"hostname_hash"` // sha256 hex of hostname, not the name
}

// ScaleInfo records what was actually exercised.
type ScaleInfo struct {
	Name            string `json:"name"`
	ReceiptsWritten int    `json:"receipts_written"`
	ReadSamples     int    `json:"read_samples"`
	ExportSamples   int    `json:"export_samples"`
}

// Metrics holds measured durations and RSS.
type Metrics struct {
	AppendTotalMS      float64       `json:"append_total_ms"`
	AppendPerReceiptUS float64       `json:"append_per_receipt_us"`
	ReadLimitedMS      PercentileSet `json:"read_limited_ms"`
	ExportBuildSealMS  PercentileSet `json:"export_build_seal_ms"`
	RSSBytesAfter      uint64        `json:"rss_bytes_after"`
}

// PercentileSet is computed from measured samples (milliseconds).
type PercentileSet struct {
	P50   float64 `json:"p50"`
	P95   float64 `json:"p95"`
	P99   float64 `json:"p99"`
	N     int     `json:"n"`
	MinMS float64 `json:"min_ms"`
	MaxMS float64 `json:"max_ms"`
}

// ResolveScale fills Receipts/samples from named presets when unset.
func ResolveScale(o Options) (Options, error) {
	name := o.Scale
	if name == "" {
		name = ScaleSmoke
	}
	switch name {
	case ScaleSmoke:
		if o.Receipts <= 0 {
			o.Receipts = 200
		}
		if o.ReadSamples <= 0 {
			o.ReadSamples = 8
		}
		if o.ExportSamples <= 0 {
			o.ExportSamples = 4
		}
	case ScaleMedium:
		if o.Receipts <= 0 {
			o.Receipts = 10_000
		}
		if o.ReadSamples <= 0 {
			o.ReadSamples = 20
		}
		if o.ExportSamples <= 0 {
			o.ExportSamples = 10
		}
	case ScaleLarge:
		if o.Receipts <= 0 {
			o.Receipts = 100_000
		}
		if o.ReadSamples <= 0 {
			o.ReadSamples = 30
		}
		if o.ExportSamples <= 0 {
			o.ExportSamples = 10
		}
	default:
		return o, fmt.Errorf("perfbaseline: unknown scale %q (smoke|medium|large)", name)
	}
	if o.Receipts < 1 || o.Receipts > 1_000_000 {
		return o, fmt.Errorf("perfbaseline: receipts %d out of range", o.Receipts)
	}
	o.Scale = name
	return o, nil
}

// Run executes the measurement and returns a Report. thresholds is always null.
func Run(o Options) (Report, error) {
	o, err := ResolveScale(o)
	if err != nil {
		return Report{}, err
	}
	dir := o.StateDir
	cleanup := false
	if dir == "" {
		dir, err = os.MkdirTemp("", "siq-perfbaseline-*")
		if err != nil {
			return Report{}, err
		}
		cleanup = true
	}
	if cleanup {
		defer os.RemoveAll(dir)
	}

	seed := o.Seed
	if len(seed) == 0 {
		seed = make([]byte, 32)
		for i := range seed {
			seed[i] = byte(i + 3)
		}
	}
	key, err := signing.FromSeed(seed)
	if err != nil {
		return Report{}, err
	}
	chain, err := receipt.OpenChain(dir, "perf", key)
	if err != nil {
		return Report{}, err
	}

	t0 := time.Now()
	for i := 0; i < o.Receipts; i++ {
		r := receipt.Receipt{
			Platform:        "hermes",
			SessionID:       fmt.Sprintf("sess-%d", i%64),
			Tool:            "read_file",
			Action:          "allow",
			Reason:          "perfbaseline",
			EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			return Report{}, fmt.Errorf("append %d: %w", i, err)
		}
	}
	appendDur := time.Since(t0)

	readSamples := make([]float64, 0, o.ReadSamples)
	for i := 0; i < o.ReadSamples; i++ {
		t1 := time.Now()
		_, err := chain.ReadLimited(receipt.ReadLimit{
			MaxRecords: export.DefaultMaxReceipts,
			MaxBytes:   64 << 20,
		})
		if err != nil {
			return Report{}, err
		}
		readSamples = append(readSamples, float64(time.Since(t1).Microseconds())/1000.0)
	}

	disk, err := chain.ReadLimited(receipt.ReadLimit{
		MaxRecords: export.DefaultMaxReceipts,
		MaxBytes:   64 << 20,
	})
	if err != nil {
		return Report{}, err
	}
	exportSamples := make([]float64, 0, o.ExportSamples)
	for i := 0; i < o.ExportSamples; i++ {
		t1 := time.Now()
		b := export.Build(export.Input{
			Now:      time.Now().UTC().Format(time.RFC3339),
			Mode:     "block",
			Key:      key,
			Snap:     ledger.Snapshot{Receipts: disk.Receipts},
			DiskRead: &disk,
		})
		if err := export.Seal(key, &b); err != nil {
			return Report{}, err
		}
		if _, err := export.MarshalJSONBytesBudget(b, export.DefaultMaxJSONBytes); err != nil {
			return Report{}, err
		}
		exportSamples = append(exportSamples, float64(time.Since(t1).Microseconds())/1000.0)
	}

	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)

	perUS := float64(0)
	if o.Receipts > 0 {
		perUS = float64(appendDur.Microseconds()) / float64(o.Receipts)
	}

	rep := Report{
		Format:     Format,
		MeasuredAt: time.Now().UTC().Format(time.RFC3339),
		Environment: Environment{
			GoVersion:    runtime.Version(),
			OS:           runtime.GOOS,
			Arch:         runtime.GOARCH,
			NumCPU:       runtime.NumCPU(),
			HostnameHash: hostnameHash(),
		},
		Scale: ScaleInfo{
			Name:            o.Scale,
			ReceiptsWritten: o.Receipts,
			ReadSamples:     o.ReadSamples,
			ExportSamples:   o.ExportSamples,
		},
		Metrics: Metrics{
			AppendTotalMS:      float64(appendDur.Microseconds()) / 1000.0,
			AppendPerReceiptUS: perUS,
			ReadLimitedMS:      percentiles(readSamples),
			ExportBuildSealMS:  percentiles(exportSamples),
			RSSBytesAfter:      ms.Sys,
		},
		Notes:      HonestyNote,
		Thresholds: nil,
	}
	return rep, nil
}

// MarshalJSON encodes the report with indent for evidence archives.
func MarshalJSON(r Report) ([]byte, error) {
	return json.MarshalIndent(r, "", "  ")
}

func hostnameHash() string {
	h, err := os.Hostname()
	if err != nil || h == "" {
		return "unknown"
	}
	sum := sha256.Sum256([]byte(h))
	return hex.EncodeToString(sum[:])
}

func percentiles(samples []float64) PercentileSet {
	out := PercentileSet{N: len(samples)}
	if len(samples) == 0 {
		return out
	}
	s := append([]float64(nil), samples...)
	sort.Float64s(s)
	out.MinMS = s[0]
	out.MaxMS = s[len(s)-1]
	out.P50 = percentileSorted(s, 50)
	out.P95 = percentileSorted(s, 95)
	out.P99 = percentileSorted(s, 99)
	return out
}

func percentileSorted(sorted []float64, p int) float64 {
	if len(sorted) == 0 {
		return 0
	}
	if p <= 0 {
		return sorted[0]
	}
	if p >= 100 {
		return sorted[len(sorted)-1]
	}
	// nearest-rank
	idx := (p*len(sorted) + 99) / 100
	if idx < 1 {
		idx = 1
	}
	if idx > len(sorted) {
		idx = len(sorted)
	}
	return sorted[idx-1]
}
