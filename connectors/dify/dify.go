// Command dify-connector is the Dify Deployment Connector
// (connector-protocol.v1.md). It discovers self-hosted Dify deployments
// (source type "dify_deployment") at the application level: Dify itself is a
// server-side docker-compose deployment, so its local footprint is a
// docker-compose.yaml / compose.yaml under the deployment directory that
// references langgenius/dify-* images (dify-api / dify-web / dify-sandbox).
//
// Security boundaries (contract §4, aligned with the directory connector):
//   - NO default scope: scanning requires explicitly administrator-authorized
//     roots; an empty scope is rejected by validate_scope.
//   - symlinks escaping the scope are skipped with a stderr warning.
//   - compose files are read under a strict byte budget (readFileLimited);
//     budget exhaustion is explicit (errBudgetExhausted + batch.Truncated).
//   - 安全红线：除 langgenius/dify 镜像引用行与 service 名之外，compose 文件
//     内容（尤其 environment 段的 secret 值）绝不进入任何输出字段；
//     evidence 的 content_hash 只对 dify 相关行计算，而非整个文件。
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
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/edge/agent/protocol"
)

const connectorVersion = "0.1.0"

// composeFileNames: Dify 自托管部署的本地足迹文件（docker-compose.ya?ml /
// compose.ya?ml）。
var composeFileNames = map[string]bool{
	"docker-compose.yaml": true,
	"docker-compose.yml":  true,
	"compose.yaml":        true,
	"compose.yml":         true,
}

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
			fmt.Fprintf(os.Stderr, "dify-connector: %v\n", err)
			os.Exit(1)
		}
		return
	}
	fmt.Fprintln(os.Stderr, "usage: dify-connector --serve")
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

type found struct {
	path string
	rel  string
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
			result = validateScopeOp(p.Scope)
		}
	case protocol.OpPlanScan:
		var p planScanParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			plan, err := planScanOp(p)
			if err != nil {
				perr = toProtocolError(err)
			} else {
				result = plan
			}
		}
	case protocol.OpCollect:
		var p collectParams
		if err := json.Unmarshal(req.Params, &p); err != nil {
			perr = badRequest(err)
		} else {
			batch, err := collectOp(p.Plan)
			if err != nil {
				perr = toProtocolError(err)
			} else {
				result = batch
			}
		}
	case protocol.OpCheckpoint:
		result = map[string]string{"cursor": lastCursor}
	case protocol.OpHealth:
		result = healthOp()
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
		Objects:             []string{"dify_deployment"},
		RequiredPermissions: []string{"read:<explicit scope required>"},
		DataCategories:      []string{"manifest_names", "image_refs"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	errs := validateScope(scope)
	return protocol.ValidationResult{Valid: len(errs) == 0, Errors: errs}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: no roots（Dify 部署发现必须显式授权 roots，本 Connector 无默认范围）"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	return nil
}

// planScanOp: 无默认范围——空范围是错误而非静默替换。
func planScanOp(p planScanParams) (protocol.ScanPlan, error) {
	if errs := validateScope(p.Scope); len(errs) > 0 {
		return protocol.ScanPlan{}, fmt.Errorf("%s", strings.Join(errs, "; "))
	}
	scope := *p.Scope
	return protocol.ScanPlan{Scope: &scope, Cursor: p.Cursor, Limits: defaultLimits()}, nil
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 200, MaxBytes: 16 * 1024 * 1024}
}

// difyService 是从 compose 文本中提取的一个 Dify 服务（仅镜像引用与
// service 名，绝不包含 environment 等其他内容）。
type difyService struct {
	name  string
	image string // 完整镜像引用，如 langgenius/dify-api:0.6.8
	tag   string // 镜像 tag，无则空
}

const difyImagePrefix = "langgenius/dify-"

// imageTokenChars 限定镜像引用 token 的合法字符集。
var imageTokenRe = regexp.MustCompile(`langgenius/dify-[A-Za-z0-9._:@-]+`)

// parseDifyServices 以纯文本行扫描 compose 内容（不引入 yaml 依赖）：
// 跟踪 services: 块内的 service 名缩进层级，把 langgenius/dify-* 镜像引用
// 归属到当前 service。只返回引用了 dify 镜像的服务。
func parseDifyServices(content string) []difyService {
	var services []difyService
	current := -1 // 当前 service 下标（append 可能扩容，不能用指针跟踪）
	inServices := false
	servicesIndent := -1
	serviceIndent := -1
	for _, raw := range strings.Split(content, "\n") {
		line := strings.TrimRight(raw, "\r")
		trimmed := strings.TrimSpace(line)
		if trimmed == "" || strings.HasPrefix(trimmed, "#") {
			continue
		}
		indent := len(line) - len(strings.TrimLeft(line, " \t"))
		if inServices && indent <= servicesIndent {
			inServices = false // 离开 services 块
		}
		if !inServices {
			if trimmed == "services:" {
				inServices = true
				servicesIndent = indent
				serviceIndent = -1
				current = -1
			}
			continue
		}
		if serviceIndent == -1 && indent > servicesIndent {
			serviceIndent = indent // 第一个 key 的缩进即 service 名层级
		}
		if indent == serviceIndent && strings.HasSuffix(trimmed, ":") {
			name := strings.TrimSuffix(trimmed, ":")
			services = append(services, difyService{name: name})
			current = len(services) - 1
			continue
		}
		if current < 0 || services[current].image != "" {
			continue
		}
		loc := imageTokenRe.FindString(line)
		if loc == "" {
			continue
		}
		image := loc
		tag := ""
		if i := strings.Index(image, "@"); i >= 0 {
			image = image[:i] // digest 引用不作为 tag
		} else if i := strings.LastIndex(image, ":"); i >= 0 {
			tag = image[i+1:]
		}
		services[current].image = image
		services[current].tag = tag
	}
	out := services[:0]
	for _, s := range services {
		if s.image != "" {
			out = append(out, s)
		}
	}
	return out
}

// difyFactsHash 只对 dify 相关行（service 名 + 镜像引用）计算事实哈希。
// 安全红线：compose 可能含其他服务的敏感环境变量，整个文件绝不进哈希输入。
func difyFactsHash(services []difyService) string {
	h := sha256.New()
	for _, s := range services {
		h.Write([]byte(s.name))
		h.Write([]byte{0})
		h.Write([]byte(s.image))
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
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
	start := time.Now()
	red := protocol.NewRedactor()
	now := time.Now().UTC().Format(time.RFC3339)

	// 收集 compose 文件清单（先走查，后读取，保证限额可控）
	var foundFiles []found
	for _, raw := range sc.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		rootBase := strings.TrimSuffix(root, "/*")
		err := filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				fmt.Fprintf(os.Stderr, "dify-connector: walk %s: %v\n", path, err)
				return nil
			}
			if d.IsDir() {
				name := d.Name()
				if path != root && (strings.HasPrefix(name, ".") || name == "node_modules" || name == "vendor") {
					return filepath.SkipDir
				}
				return nil
			}
			if !composeFileNames[d.Name()] {
				return nil
			}
			if escaped, _ := symlinkEscapes(rootBase, path); escaped {
				fmt.Fprintf(os.Stderr, "dify-connector: skipping %s: symlink escapes scope\n", path)
				return nil
			}
			rel, _ := filepath.Rel(rootBase, path)
			foundFiles = append(foundFiles, found{path: path, rel: rel})
			return nil
		})
		if err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("walk %s: %w", root, err)
		}
	}
	sort.Slice(foundFiles, func(i, j int) bool { return foundFiles[i].rel < foundFiles[j].rel })

	batch := protocol.EvidenceBatch{
		Candidates: []*protocol.Candidate{},
		Evidence:   []*protocol.Evidence{},
	}
	var readBytes int64
	deployments := 0
	for _, f := range foundFiles {
		if int64(deployments) >= limits.MaxFiles {
			batch.Truncated = true
			break
		}
		if opTimeout > 0 && time.Since(start) > opTimeout {
			batch.Truncated = true
			break
		}
		remaining := limits.MaxBytes - readBytes
		if remaining <= 0 {
			// 预算耗尽：显式截断，不读下一文件
			batch.Truncated = true
			break
		}
		data, err := readFileLimited(f.path, remaining)
		if errors.Is(err, errBudgetExhausted) {
			batch.Truncated = true
			break
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "dify-connector: read %s: %v\n", f.path, err)
			continue
		}
		readBytes += int64(len(data))
		if readBytes > limits.MaxBytes {
			batch.Truncated = true
			break
		}
		// 文件内容被预算截断：不完整内容不得误当完整 compose 分析
		if fi, statErr := os.Stat(f.path); statErr == nil && fi.Size() > int64(len(data)) {
			batch.Truncated = true
			continue
		}

		services := parseDifyServices(string(data))
		if len(services) == 0 {
			continue // 非 dify compose：跳过，不是错误
		}

		dirName := filepath.Base(filepath.Dir(f.path))
		if dirName == "." || dirName == string(filepath.Separator) || dirName == "" {
			dirName = "root"
		}
		names := make([]string, 0, len(services))
		apiVersion := ""
		for _, s := range services {
			names = append(names, s.name)
			if s.image == "langgenius/dify-api" || strings.HasPrefix(s.image, "langgenius/dify-api:") {
				if apiVersion == "" {
					apiVersion = s.tag
				}
			}
		}
		relHash := sha256.Sum256([]byte(f.rel))
		evidenceID := "ev:dify:" + hex.EncodeToString(relHash[:])[:16]
		attrs := map[string]string{
			"compose_file":    f.rel,
			"services":        red.RedactString(strings.Join(names, ",")),
			"discovery_basis": "compose_manifest",
		}
		if apiVersion != "" {
			attrs["api_version"] = apiVersion
		}
		cand := &protocol.Candidate{
			CandidateID:   "dify:" + f.rel,
			SourceType:    "dify_deployment",
			SourceLocator: red.RedactString("dify://" + f.rel),
			DiscoveredAt:  now,
			Name:          truncate(red.RedactString(dirName), 256),
			Framework:     "dify",
			Confidence:    0.9,
			Attributes:    attrs,
			EvidenceIDs:   []string{evidenceID},
		}
		batch.Candidates = append(batch.Candidates, cand)
		batch.Evidence = append(batch.Evidence, &protocol.Evidence{
			EvidenceID:       evidenceID,
			SourceType:       "manifest",
			SourceLocator:    red.RedactString(f.rel),
			ObservedAt:       now,
			CollectedAt:      now,
			CollectorID:      "", // Edge 收包后补齐（合同 §4）
			ConnectorVersion: connectorVersion,
			ContentHash:      difyFactsHash(services),
			RedactionProfile: protocol.RedactionProfile,
			Classification:   "internal",
			SubjectRef:       strPtr(cand.CandidateID),
		})
		deployments++
	}
	if len(foundFiles) > 0 {
		lastCursor = "dify-cursor:" + computeCursor(foundFiles, batch.Evidence)
	}
	return batch, nil
}

// computeCursor: 稳定增量游标（相对路径 + 事实哈希，不以墙钟时间为依据）。
func computeCursor(files []found, evidence []*protocol.Evidence) string {
	h := sha256.New()
	byID := map[string]string{}
	for _, ev := range evidence {
		if ev.SubjectRef != nil {
			byID[*ev.SubjectRef] = ev.ContentHash
		}
	}
	for _, f := range files {
		h.Write([]byte(f.rel))
		h.Write([]byte{0})
		h.Write([]byte(byID["dify:"+f.rel]))
		h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

func healthOp() protocol.HealthReport {
	return protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{}}
}

// errBudgetExhausted: 剩余字节预算为 0 时的显式结果。
// 预算耗尽必须表现为 truncated/skipped，禁止回退到默认大小继续读取。
var errBudgetExhausted = errors.New("byte budget exhausted")

func readFileLimited(path string, maxBytes int64) ([]byte, error) {
	if maxBytes <= 0 {
		return nil, errBudgetExhausted
	}
	f, err := openRegular(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return nil, err
	}
	if !st.Mode().IsRegular() {
		return nil, errors.New("non-regular file refused after open")
	}
	data, err := io.ReadAll(io.LimitReader(f, maxBytes))
	if err != nil {
		return nil, err
	}
	return data, nil
}

func symlinkEscapes(root, p string) (bool, error) {
	rp, err := filepath.EvalSymlinks(p)
	if err != nil {
		return false, err
	}
	rr, err := filepath.EvalSymlinks(root)
	if err != nil {
		return false, err
	}
	rel, err := filepath.Rel(rr, rp)
	if err != nil {
		return false, err
	}
	return rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)), nil
}

func strPtr(s string) *string {
	return &s
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

func badRequest(err error) *protocol.ProtocolError {
	return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: err.Error()}
}

func toProtocolError(err error) *protocol.ProtocolError {
	msg := err.Error()
	code := protocol.CodeUnsupported
	switch {
	case strings.Contains(msg, "empty scope"):
		code = protocol.CodeScopeInvalid
	case strings.Contains(msg, "symlink"):
		code = protocol.CodeScopeInvalid
	}
	return &protocol.ProtocolError{Code: code, Message: msg}
}
