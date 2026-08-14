// Command openclaw-connector is the OpenClaw Agent Connector (L1/L2, read-only;
// connector-protocol.v1.md). It discovers agents declared in ~/.openclaw
// (openclaw.json agents.list + per-agent agentDir) and emits candidates,
// evidence, and DECLARED permission facts (model routing / workspace).
//
// Security boundaries (design doc §16.3 / contract §4):
//   - READ-ONLY: this connector never writes OpenClaw config; enforcement goes
//     through the OpenShell layer, never OpenClaw's own management plane.
//   - auth-profiles.json / sessions / .env are NEVER read: secret_ref evidence
//     records only name+size.
//   - apiKey values are environment-variable references and are redacted anyway.
//   - NO default scope: explicit authorized roots required.
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

var defaultIncludes = []string{"openclaw.json"}

var (
	lastCursor string
	opTimeout  time.Duration
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--serve" {
		if ms := os.Getenv("SIQ_CONNECTOR_TIMEOUT_MS"); ms != "" {
			if v, err := strconv.Atoi(ms); err == nil && v > 0 {
				opTimeout = time.Duration(v) * time.Millisecond
			}
		}
		if opTimeout <= 0 {
			opTimeout = time.Duration(protocol.DefaultCollectTimeoutMS) * time.Millisecond
		}
		if err := serve(); err != nil {
			fmt.Fprintf(os.Stderr, "openclaw-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: openclaw-connector --serve")
	os.Exit(2)
}

func serve() error {
	dec := json.NewDecoder(bufio.NewReader(os.Stdin))
	w := bufio.NewWriter(os.Stdout)
	for {
		var req protocol.Request
		if err := dec.Decode(&req); err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read request: %w", err)
		}
		line, err := json.Marshal(dispatch(&req))
		if err != nil {
			return fmt.Errorf("encode response: %w", err)
		}
		if _, err := w.Write(append(line, '\n')); err != nil {
			return err
		}
		if err := w.Flush(); err != nil {
			return err
		}
	}
}

type validateScopeParams struct {
	Scope *protocol.Scope `json:"scope"`
}

type planScanParams struct {
	Scope  *protocol.Scope `json:"scope"`
	Cursor string          `json:"cursor,omitempty"`
}

type collectParams struct {
	Plan protocol.ScanPlan `json:"plan"`
}

func dispatch(req *protocol.Request) protocol.Response {
	resp := protocol.Response{ID: req.ID, OK: true}
	var result any
	var perr *protocol.ProtocolError
	switch req.Op {
	case protocol.OpDescribe:
		result = capabilities()
	case protocol.OpValidateScope:
		var p validateScopeParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			result = protocol.ValidationResult{Valid: true, Errors: validateScope(p.Scope)}
		}
	case protocol.OpPlanScan:
		var p planScanParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else if errs := validateScope(p.Scope); len(errs) > 0 {
			perr = &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: strings.Join(errs, "; ")}
		} else {
			scope := *p.Scope
			if len(scope.Include) == 0 {
				scope.Include = defaultIncludes
			}
			result = protocol.ScanPlan{Scope: &scope, Cursor: p.Cursor, Limits: defaultLimits()}
		}
	case protocol.OpCollect:
		var p collectParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			batch, err := collectOp(p.Plan)
			if err != nil {
				perr = &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: err.Error()}
			} else {
				result = batch
			}
		}
	case protocol.OpCheckpoint:
		result = map[string]string{"cursor": lastCursor}
	case protocol.OpHealth:
		result = protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{}}
	default:
		perr = &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: fmt.Sprintf("unknown op: %s", req.Op)}
	}
	if perr != nil {
		resp.OK = false
		resp.Error = perr
	} else {
		resp.Result = result
	}
	return resp
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"openclaw_agent"},
		RequiredPermissions: []string{"read:<explicit openclaw config root>"},
		DataCategories:      []string{"agent_names", "model_ids", "workspace_paths"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: no roots（OpenClaw 配置目录必须显式授权）"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	return nil
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

// openclawConfig mirrors the subset of openclaw.json we read (declared facts only).
type openclawConfig struct {
	Agents struct {
		List []struct {
			ID        string `json:"id"`
			Name      string `json:"name"`
			Workspace string `json:"workspace"`
			AgentDir  string `json:"agentDir"`
			Model     any    `json:"model"`
		} `json:"list"`
	} `json:"agents"`
}

func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	sc := plan.Scope
	if sc == nil || len(sc.Roots) == 0 {
		return protocol.EvidenceBatch{}, fmt.Errorf("empty scope: no roots")
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	red := protocol.NewRedactor()
	now := time.Now().UTC().Format(time.RFC3339)

	batch := protocol.EvidenceBatch{
		Candidates:      []*protocol.Candidate{},
		Evidence:        []*protocol.Evidence{},
		PermissionFacts: []*protocol.PermissionFact{},
	}
	var readBytes int64
	for _, raw := range sc.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		cfgPath := filepath.Join(root, "openclaw.json")
		data, err := readFileLimited(cfgPath, limits.MaxBytes-readBytes)
		if err != nil {
			fmt.Fprintf(os.Stderr, "openclaw-connector: read %s: %v\n", cfgPath, err)
			continue
		}
		readBytes += int64(len(data))
		var cfg openclawConfig
		if err := json.Unmarshal(data, &cfg); err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("openclaw.json 解析失败: %w", err)
		}

		cfgHash := protocol.ContentHash(data)
		for _, agent := range cfg.Agents.List {
			name := agent.Name
			if name == "" {
				name = agent.ID
			}
			if name == "" {
				continue
			}
			evidenceID := "ev:openclaw:" + hex.EncodeToString([]byte(agent.ID+cfgHash))[:16]
			cand := &protocol.Candidate{
				CandidateID:   "openclaw:" + name,
				SourceType:    "openclaw_agent",
				SourceLocator: red.RedactString("openclaw://agents/" + name),
				DiscoveredAt:  now,
				Name:          truncate(red.RedactString(name), 256),
				Framework:     "openclaw",
				Confidence:    1.0,
				EvidenceIDs:   []string{evidenceID},
			}
			attrs := map[string]string{}
			if agent.Workspace != "" {
				attrs["workspace"] = red.RedactString(agent.Workspace)
			}
			if agent.AgentDir != "" {
				attrs["agent_dir"] = red.RedactString(agent.AgentDir)
			}
			modelIDs := extractModelIDs(agent.Model)
			if len(modelIDs) > 0 {
				attrs["models"] = red.RedactString(strings.Join(modelIDs, ","))
			}
			cand.Attributes = attrs
			batch.Candidates = append(batch.Candidates, cand)
			batch.Evidence = append(batch.Evidence, &protocol.Evidence{
				EvidenceID:       evidenceID,
				SourceType:       "openclaw_config",
				SourceLocator:    red.RedactString(filepath.Join(root, "openclaw.json")),
				ObservedAt:       now,
				CollectedAt:      now,
				ConnectorVersion: connectorVersion,
				ContentHash:      cfgHash,
				RedactionProfile: "siq.redaction.v1",
				Classification:   "internal",
				SubjectRef:       strPtr(cand.CandidateID),
			})

			// declared 权限事实（绝不 effective；权威源解析另行完成）
			for _, mid := range modelIDs {
				batch.PermissionFacts = append(batch.PermissionFacts, &protocol.PermissionFact{
					Subject:    &protocol.Subject{Type: "agent_asset", ID: cand.CandidateID},
					Domain:     "model",
					Action:     "model.generate",
					Resource:   &protocol.Resource{Type: "model", Value: red.RedactString(mid)},
					Effect:     "allow",
					State:      "declared",
					Authority:  "openclaw-config",
					EvidenceIDs: []string{evidenceID},
				})
			}
			if agent.Workspace != "" {
				batch.PermissionFacts = append(batch.PermissionFacts, &protocol.PermissionFact{
					Subject:    &protocol.Subject{Type: "agent_asset", ID: cand.CandidateID},
					Domain:     "filesystem",
					Action:     "fs.write",
					Resource:   &protocol.Resource{Type: "path", Value: red.RedactString(agent.Workspace)},
					Effect:     "allow",
					State:      "declared",
					Authority:  "openclaw-config",
					EvidenceIDs: []string{evidenceID},
				})
			}
		}

		// auth-profiles.json 等敏感文件：secret_ref 证据（只记名字+大小，永不读内容）
		authProfile := filepath.Join(root, "agents", "auth-profiles.json")
		if fi, err := os.Stat(authProfile); err == nil {
			batch.Evidence = append(batch.Evidence, &protocol.Evidence{
				EvidenceID:       "ev:openclaw:auth-profiles",
				SourceType:       "manifest",
				SourceLocator:    "agents/auth-profiles.json",
				ObservedAt:       now,
				CollectedAt:      now,
				ConnectorVersion: connectorVersion,
				ContentHash:      fmt.Sprintf("size:%d", fi.Size()), // 只记大小，内容永不哈希
				RedactionProfile: "siq.redaction.v1",
				Classification:   "secret_ref",
			})
		}
	}
	if len(batch.Candidates) > 0 {
		h := sha256.New()
		for _, c := range batch.Candidates {
			h.Write([]byte(c.CandidateID))
			h.Write([]byte{0})
		}
		lastCursor = "openclaw-cursor:" + hex.EncodeToString(h.Sum(nil))
	}
	return batch, nil
}

// extractModelIDs pulls model identifiers from the polymorphic `model` field
// (string "provider/model", {"primary": ..., "fallbacks": [...]}).
func extractModelIDs(model any) []string {
	var out []string
	switch v := model.(type) {
	case string:
		if v != "" {
			out = append(out, v)
		}
	case map[string]any:
		for _, key := range []string{"primary"} {
			if s, ok := v[key].(string); ok && s != "" {
				out = append(out, s)
			}
		}
		if fallbacks, ok := v["fallbacks"].([]any); ok {
			for _, f := range fallbacks {
				if s, ok := f.(string); ok && s != "" {
					out = append(out, s)
				}
			}
		}
	}
	return out
}

func readFileLimited(path string, maxBytes int64) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	if maxBytes <= 0 {
		maxBytes = 1 << 20
	}
	return io.ReadAll(io.LimitReader(f, maxBytes))
}

func strPtr(s string) *string { return &s }

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: err.Error()}
}
