// Command perfbaseline measures local receipt-chain / export observations (DEV16-D).
//
//	go run ./cmd/perfbaseline -scale smoke -out /tmp/perf.json
//	go run ./cmd/perfbaseline -scale medium -out docs/evidence/perf/local-medium.json
//
// Output never encodes SLA pass/fail. Large scales are operator-run; CI uses smoke.
package main

import (
	"flag"
	"fmt"
	"os"

	"siq-agent-security/apps/agentshield/internal/perfbaseline"
)

func main() {
	scale := flag.String("scale", perfbaseline.ScaleSmoke, "smoke|medium|large")
	receipts := flag.Int("receipts", 0, "override receipt count (0 = scale default)")
	out := flag.String("out", "", "write JSON report (default stdout)")
	flag.Parse()

	rep, err := perfbaseline.Run(perfbaseline.Options{
		Scale:    *scale,
		Receipts: *receipts,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "perfbaseline: %v\n", err)
		os.Exit(1)
	}
	raw, err := perfbaseline.MarshalJSON(rep)
	if err != nil {
		fmt.Fprintf(os.Stderr, "perfbaseline: marshal: %v\n", err)
		os.Exit(1)
	}
	raw = append(raw, '\n')
	if *out == "" {
		_, _ = os.Stdout.Write(raw)
		return
	}
	if err := os.WriteFile(*out, raw, 0o600); err != nil {
		fmt.Fprintf(os.Stderr, "perfbaseline: write: %v\n", err)
		os.Exit(1)
	}
}
