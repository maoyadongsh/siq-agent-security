package perfbaseline

import (
	"encoding/json"
	"testing"
)

func TestIntentBaselineScaleAndMissingLookup(t *testing.T) {
	for _, args := range [][2]int{{0, 1}, {4097, 1}, {1, 0}, {1, 10001}} {
		if _, err := MeasureIntentScale(args[0], args[1]); err == nil {
			t.Fatal("accepted invalid scale", args)
		}
	}
	raw, err := MeasureIntentScale(3, 4)
	if err != nil {
		t.Fatal(err)
	}
	var report struct {
		Bindings int
		Samples  int
		Lookup   map[string]float64 `json:"lookup_ms"`
		Missing  map[string]float64 `json:"missing_lookup_ms"`
	}
	if err = json.Unmarshal(raw, &report); err != nil {
		t.Fatal(err)
	}
	if report.Bindings != 3 || report.Samples != 4 || len(report.Lookup) == 0 || len(report.Missing) == 0 {
		t.Fatal(string(raw))
	}
}
