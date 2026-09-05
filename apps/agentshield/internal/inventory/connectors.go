package inventory

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
)

const (
	connectorTimeout = 60 * time.Second
	connectorMaxOut  = 8 << 20
)

var connectorNames = []string{"hermes", "openclaw", "directory", "mcp"}

func (r *run) mergeConnectors() {
	dir := strings.TrimSpace(r.opts.ConnectorsDir)
	if dir == "" {
		return
	}
	info, err := os.Stat(dir)
	if err != nil || !info.IsDir() {
		r.report.Skipped = append(r.report.Skipped, "connectors_dir_unreadable")
		return
	}
	haveCand := map[string]bool{}
	haveEv := map[string]bool{}
	for _, c := range r.report.Candidates {
		haveCand[c.CandidateID] = true
	}
	for _, e := range r.report.Evidence {
		haveEv[e.EvidenceID] = true
	}
	for _, name := range connectorNames {
		bin, err := findConnectorBin(dir, name)
		if err != nil {
			r.report.Skipped = append(r.report.Skipped, "connector_missing:"+name)
			continue
		}
		batch, err := execConnector(bin, name, r.opts.Home)
		if err != nil {
			r.report.Skipped = append(r.report.Skipped, "connector_failed:"+name)
			continue
		}
		for _, c := range batch.Candidates {
			if c.CandidateID == "" || haveCand[c.CandidateID] {
				continue
			}
			haveCand[c.CandidateID] = true
			r.report.Candidates = append(r.report.Candidates, c)
		}
		for _, e := range batch.Evidence {
			if e.EvidenceID == "" || haveEv[e.EvidenceID] {
				continue
			}
			if e.Signature == "" {
				e.Signature = signDoc(r.opts.Key, e)
			}
			haveEv[e.EvidenceID] = true
			r.report.Evidence = append(r.report.Evidence, e)
		}
		for _, f := range batch.Facts {
			if f.State == "effective" {
				continue
			}
			r.report.Facts = append(r.report.Facts, f)
		}
	}
}

func findConnectorBin(root, name string) (string, error) {
	cands := []string{
		filepath.Join(root, name, name+"-connector"),
		filepath.Join(root, name, name),
		filepath.Join(root, name+"-connector"),
		filepath.Join(root, name),
	}
	for _, p := range cands {
		st, err := os.Stat(p)
		if err != nil || st.IsDir() || st.Mode()&0o111 == 0 {
			continue
		}
		return p, nil
	}
	return "", os.ErrNotExist
}

type connectorBatch struct {
	Candidates []Candidate
	Evidence   []admission.Evidence
	Facts      []Fact
}

func execConnector(bin, name, home string) (connectorBatch, error) {
	ctx, cancel := context.WithTimeout(context.Background(), connectorTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, bin, "--serve")
	cmd.Env = []string{
		"SIQ_CONNECTOR_NAME=" + name,
		"SIQ_CONNECTOR_VERSION=0.1.0",
		"SIQ_CONNECTOR_TIMEOUT_MS=60000",
		"HOME=" + home,
		"PATH=" + os.Getenv("PATH"),
	}
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return connectorBatch{}, err
	}
	var stdout bytes.Buffer
	cmd.Stdout = &limitWriter{w: &stdout, n: connectorMaxOut}
	cmd.Stderr = io.Discard
	if err := cmd.Start(); err != nil {
		return connectorBatch{}, err
	}
	reqs := []map[string]any{
		{"id": "1", "op": "describe", "params": map[string]any{}},
		{"id": "2", "op": "collect", "params": map[string]any{
			"plan": map[string]any{
				"scope":  map[string]any{"roots": []string{home}},
				"limits": map[string]any{"max_files": 200, "max_bytes": 16777216},
			},
		}},
	}
	enc := json.NewEncoder(stdin)
	for _, req := range reqs {
		if err := enc.Encode(req); err != nil {
			_ = stdin.Close()
			_ = cmd.Wait()
			return connectorBatch{}, err
		}
	}
	_ = stdin.Close()
	waitErr := cmd.Wait()
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return connectorBatch{}, fmt.Errorf("timeout")
	}
	lines := bytes.Split(bytes.TrimSpace(stdout.Bytes()), []byte("\n"))
	var desc, collect map[string]any
	for _, line := range lines {
		if len(bytes.TrimSpace(line)) == 0 {
			continue
		}
		var msg map[string]any
		if json.Unmarshal(line, &msg) != nil {
			continue
		}
		switch fmt.Sprint(msg["id"]) {
		case "1":
			desc = msg
		case "2":
			collect = msg
		}
	}
	if desc == nil || !asBool(desc["ok"]) {
		if waitErr != nil {
			return connectorBatch{}, waitErr
		}
		return connectorBatch{}, errors.New("describe failed")
	}
	if result, _ := desc["result"].(map[string]any); asBool(result["network_access"]) {
		return connectorBatch{}, errors.New("network_access")
	}
	if collect == nil || !asBool(collect["ok"]) {
		return connectorBatch{}, errors.New("collect failed")
	}
	result, _ := collect["result"].(map[string]any)
	return parseCollectResult(result), nil
}

func parseCollectResult(result map[string]any) connectorBatch {
	var out connectorBatch
	if result == nil {
		return out
	}
	raw, _ := json.Marshal(result)
	var wire struct {
		Candidates []Candidate          `json:"candidates"`
		Evidence   []admission.Evidence `json:"evidence"`
		Facts      []Fact               `json:"permission_facts"`
	}
	_ = json.Unmarshal(raw, &wire)
	for _, c := range wire.Candidates {
		if c.CandidateID == "" || c.SourceType == "" || len(c.EvidenceIDs) == 0 {
			continue
		}
		if c.Status == "" {
			c.Status = "candidate"
		}
		out.Candidates = append(out.Candidates, c)
	}
	for _, e := range wire.Evidence {
		if e.EvidenceID == "" || e.ContentHash == "" {
			continue
		}
		out.Evidence = append(out.Evidence, e)
	}
	for _, f := range wire.Facts {
		if f.State == "effective" {
			continue
		}
		out.Facts = append(out.Facts, f)
	}
	return out
}

func asBool(v any) bool {
	b, _ := v.(bool)
	return b
}

type limitWriter struct {
	w *bytes.Buffer
	n int
}

func (l *limitWriter) Write(p []byte) (int, error) {
	if l.w.Len()+len(p) > l.n {
		return 0, errors.New("output limit")
	}
	return l.w.Write(p)
}
