package perfbaseline

import (
	"encoding/json"
	"runtime"
	"testing"
)

func TestResolveScalePresets(t *testing.T) {
	o, err := ResolveScale(Options{Scale: ScaleSmoke})
	if err != nil || o.Receipts != 200 {
		t.Fatalf("smoke: %+v %v", o, err)
	}
	o, err = ResolveScale(Options{Scale: ScaleMedium})
	if err != nil || o.Receipts != 10_000 {
		t.Fatalf("medium: %+v %v", o, err)
	}
	o, err = ResolveScale(Options{Scale: ScaleLarge})
	if err != nil || o.Receipts != 100_000 {
		t.Fatalf("large: %+v %v", o, err)
	}
	if _, err := ResolveScale(Options{Scale: "xlarge"}); err == nil {
		t.Fatal("unknown scale must fail")
	}
}

func TestUnavailableRSSSerializesNull(t *testing.T) {
	raw, err := json.Marshal(map[string]any{"rss_bytes_after": rssValue(0, false), "rss_source": "unavailable"})
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err = json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if value, ok := doc["rss_bytes_after"]; !ok || value != nil {
		t.Fatal("unavailable RSS must not be fake zero")
	}
}

func TestPercentilesNearestRank(t *testing.T) {
	// 1..100 → p50=50, p95=95, p99=99
	s := make([]float64, 100)
	for i := range s {
		s[i] = float64(i + 1)
	}
	p := percentiles(s)
	if p.P50 != 50 || p.P95 != 95 || p.P99 != 99 {
		t.Fatalf("got %+v", p)
	}
}

func TestRunSmokeProducesHonestReport(t *testing.T) {
	rep, err := Run(Options{Scale: ScaleSmoke, Receipts: 40, ReadSamples: 3, ExportSamples: 2})
	if err != nil {
		t.Fatal(err)
	}
	if rep.Format != Format {
		t.Fatalf("format %q", rep.Format)
	}
	if rep.Thresholds != nil {
		t.Fatal("thresholds must be null — no SLA pass/fail")
	}
	if rep.Notes != HonestyNote {
		t.Fatalf("honesty note missing: %q", rep.Notes)
	}
	if rep.Scale.ReceiptsWritten != 40 {
		t.Fatalf("receipts %d", rep.Scale.ReceiptsWritten)
	}
	if rep.Metrics.ReadLimitedMS.N != 3 || rep.Metrics.ExportBuildSealMS.N != 2 {
		t.Fatalf("samples: %+v", rep.Metrics)
	}
	if rep.Metrics.AppendTotalMS <= 0 || rep.Environment.GoVersion == "" {
		t.Fatalf("incomplete metrics/env: %+v", rep)
	}
	// O04-D: RSS must come from the OS (VmRSS), not runtime.MemStats.Sys.
	// On Linux the reading is always available; elsewhere it must be recorded
	// as not measured ("unavailable") rather than substituted with a wrong
	// number. go_memstats_sys_bytes is kept as a Go-runtime observation only.
	if runtime.GOOS == "linux" {
		if rep.Metrics.RSSSource != "os_vm_rss" || rep.Metrics.RSSBytesAfter == nil || *rep.Metrics.RSSBytesAfter == 0 {
			t.Fatalf("linux RSS must be os_vm_rss and >0: %+v", rep.Metrics)
		}
	} else if rep.Metrics.RSSSource != "unavailable" || rep.Metrics.RSSBytesAfter != nil {
		t.Fatalf("non-linux RSS must be unavailable/null: %+v", rep.Metrics)
	}
	if rep.Metrics.GoSysBytes == 0 {
		t.Fatalf("go_memstats_sys_bytes observation missing: %+v", rep.Metrics)
	}
	raw, err := MarshalJSON(rep)
	if err != nil {
		t.Fatal(err)
	}
	var round Report
	if err := json.Unmarshal(raw, &round); err != nil {
		t.Fatal(err)
	}
	if round.Thresholds != nil {
		t.Fatalf("JSON thresholds must decode as null, got %#v", round.Thresholds)
	}
}
