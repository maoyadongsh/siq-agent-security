// Command siq-connector consumes the local, versioned security projection
// emitted by the SIQ business API. It never receives credentials, opens a
// network connection, imports business code, or reads a sibling database.
package main

import (
	"bufio"
	"bytes"
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

const (
	connectorVersion = "0.1.0"
	eventSchema      = "siq.business-security-event/v1"
	eventProducer    = "siq-research-api"
)

var (
	lastCursor string
	opTimeout  time.Duration
	hashRefRE  = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
	digestRE   = regexp.MustCompile(`^[0-9a-f]{64}$`)
	eventIDRE  = regexp.MustCompile(`^sev_[0-9a-f]{64}$`)
	profileRE  = regexp.MustCompile(`^[a-z][a-z0-9_]{0,63}$`)
)

var (
	errScope        = errors.New("invalid SIQ security export scope")
	errInvalidEvent = errors.New("invalid SIQ business security event")
	errBudget       = errors.New("collection byte budget exhausted")
)

type hashIdentity struct {
	TenantRef  string `json:"tenant_ref"`
	SubjectRef string `json:"subject_ref"`
}

type authorizationProjection struct {
	ScopeTenantRef              string `json:"scope_tenant_ref"`
	DataScopeRefSHA256          string `json:"data_scope_ref_sha256"`
	AuthorizationSnapshotSHA256 string `json:"authorization_snapshot_sha256"`
	DataClassification          string `json:"data_classification"`
}

type executionProjection struct {
	RunRef           string `json:"run_ref"`
	SessionRef       string `json:"session_ref"`
	Profile          string `json:"profile"`
	RuntimeTarget    string `json:"runtime_target"`
	SandboxRef       string `json:"sandbox_ref"`
	ModelRouteSHA256 string `json:"model_route_sha256"`
}

type auditProjection struct {
	CorrelationRef string  `json:"correlation_ref"`
	AuditTraceRef  *string `json:"audit_trace_ref"`
}

type lifecycleProjection struct {
	Status                    string `json:"status"`
	RuntimeTerminalConfirmed  bool   `json:"runtime_terminal_confirmed"`
	ChildrenTerminalConfirmed bool   `json:"children_terminal_confirmed"`
	WriteQuiesced             bool   `json:"write_quiesced"`
}

type businessSecurityEvent struct {
	SchemaVersion string                  `json:"schema_version"`
	EventID       string                  `json:"event_id"`
	EventType     string                  `json:"event_type"`
	OccurredAt    string                  `json:"occurred_at"`
	Producer      string                  `json:"producer"`
	Identity      hashIdentity            `json:"identity"`
	Authorization authorizationProjection `json:"authorization"`
	Execution     executionProjection     `json:"execution"`
	Audit         auditProjection         `json:"audit"`
	Lifecycle     lifecycleProjection     `json:"lifecycle"`
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

func main() {
	if len(os.Args) != 2 || os.Args[1] != "--serve" {
		fmt.Fprintln(os.Stderr, "usage: siq-connector --serve")
		os.Exit(2)
	}
	if raw := os.Getenv("SIQ_CONNECTOR_TIMEOUT_MS"); raw != "" {
		if value, err := strconv.Atoi(raw); err == nil && value > 0 {
			opTimeout = time.Duration(value) * time.Millisecond
		}
	}
	if opTimeout <= 0 {
		opTimeout = time.Duration(protocol.DefaultCollectTimeoutMS) * time.Millisecond
	}
	if err := serve(); err != nil {
		fmt.Fprintf(os.Stderr, "siq-connector: %v\n", err)
		os.Exit(1)
	}
}

func serve() error {
	decoder := json.NewDecoder(bufio.NewReader(os.Stdin))
	writer := bufio.NewWriter(os.Stdout)
	for {
		var request protocol.Request
		if err := decoder.Decode(&request); err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return fmt.Errorf("read request: %w", err)
		}
		line, err := json.Marshal(dispatch(&request))
		if err != nil {
			return fmt.Errorf("encode response: %w", err)
		}
		if _, err := writer.Write(append(line, '\n')); err != nil {
			return err
		}
		if err := writer.Flush(); err != nil {
			return err
		}
	}
}

func dispatch(request *protocol.Request) protocol.Response {
	response := protocol.Response{ID: request.ID, OK: true}
	var result any
	var protocolErr *protocol.ProtocolError
	switch request.Op {
	case protocol.OpDescribe:
		result = capabilities()
	case protocol.OpValidateScope:
		var params validateScopeParams
		if err := json.Unmarshal(request.Params, &params); err != nil {
			protocolErr = &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: "malformed scope parameters"}
		} else {
			result = validateScopeOp(params.Scope)
		}
	case protocol.OpPlanScan:
		var params planScanParams
		if err := json.Unmarshal(request.Params, &params); err != nil {
			protocolErr = &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: "malformed plan parameters"}
		} else if plan, err := planScanOp(params); err != nil {
			protocolErr = toProtocolError(err)
		} else {
			result = plan
		}
	case protocol.OpCollect:
		var params collectParams
		if err := json.Unmarshal(request.Params, &params); err != nil {
			protocolErr = &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: "malformed collect parameters"}
		} else if batch, err := collectOp(params.Plan); err != nil {
			protocolErr = toProtocolError(err)
		} else {
			result = batch
		}
	case protocol.OpCheckpoint:
		result = protocol.CursorResult{Cursor: lastCursor}
	case protocol.OpHealth:
		result = protocol.HealthReport{Version: connectorVersion, Dependencies: []protocol.DependencyHealth{}}
	default:
		protocolErr = &protocol.ProtocolError{Code: protocol.CodeUnsupported, Message: "unsupported operation"}
	}
	if protocolErr != nil {
		response.OK = false
		response.Error = protocolErr
		return response
	}
	response.Result = result
	return response
}

func capabilities() protocol.ConnectorCapabilities {
	return protocol.ConnectorCapabilities{
		Version:             connectorVersion,
		Objects:             []string{"siq_business_agent_binding"},
		RequiredPermissions: []string{"read:<explicit SIQ security export root>"},
		DataCategories:      []string{"hashed_identity_refs", "authorization_digests", "run_lifecycle"},
		MaxOutputBytes:      protocol.DefaultOutputLimitBytes,
		NetworkAccess:       false,
	}
}

func defaultLimits() protocol.CollectLimits {
	return protocol.CollectLimits{MaxFiles: 500, MaxBytes: 16 * 1024 * 1024}
}

func validateScopeOp(scope *protocol.Scope) protocol.ValidationResult {
	errs := validateScope(scope)
	return protocol.ValidationResult{Valid: len(errs) == 0, Errors: errs}
}

func validateScope(scope *protocol.Scope) []string {
	if scope == nil || len(scope.Roots) == 0 {
		return []string{"empty scope: explicit SIQ security export root required"}
	}
	if err := protocol.ValidateScopeSafety(scope); err != nil {
		return []string{err.Error()}
	}
	for _, raw := range scope.Roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		if strings.ContainsAny(root, "*?[{") {
			return []string{"wildcards are not allowed for SIQ security export roots"}
		}
		info, err := os.Lstat(root)
		if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return []string{"SIQ security export root must be a real directory"}
		}
		resolved, err := filepath.EvalSymlinks(root)
		if err != nil || filepath.Clean(resolved) != filepath.Clean(root) {
			return []string{"SIQ security export root path must not traverse symlinks"}
		}
		if err := validatePrivateOwner(info); err != nil {
			return []string{"SIQ security export root must be owner-only"}
		}
	}
	return nil
}

func planScanOp(params planScanParams) (protocol.ScanPlan, error) {
	if errs := validateScope(params.Scope); len(errs) > 0 {
		return protocol.ScanPlan{}, fmt.Errorf("%w: %s", errScope, strings.Join(errs, "; "))
	}
	scope := *params.Scope
	return protocol.ScanPlan{Scope: &scope, Cursor: params.Cursor, Limits: defaultLimits()}, nil
}

type eventFile struct {
	path string
	name string
}

type candidateAccumulator struct {
	candidateID string
	profile     string
	tenantRef   string
	subjectRef  string
	scopeDigest string
	authDigest  string
	modelDigest string
	class       string
	evidenceIDs []string
	eventTypes  map[string]bool
	statuses    map[string]bool
	observedAt  string
}

func collectOp(plan protocol.ScanPlan) (protocol.EvidenceBatch, error) {
	if errs := validateScope(plan.Scope); len(errs) > 0 {
		return protocol.EvidenceBatch{}, fmt.Errorf("%w: invalid scope", errScope)
	}
	limits := plan.Limits
	if limits.MaxFiles <= 0 {
		limits.MaxFiles = defaultLimits().MaxFiles
	}
	if limits.MaxBytes <= 0 {
		limits.MaxBytes = defaultLimits().MaxBytes
	}
	started := time.Now()
	files, err := listEventFiles(plan.Scope.Roots)
	if err != nil {
		return protocol.EvidenceBatch{}, err
	}
	batch := protocol.EvidenceBatch{
		Candidates:      []*protocol.Candidate{},
		Evidence:        []*protocol.Evidence{},
		PermissionFacts: []*protocol.PermissionFact{},
	}
	accumulators := map[string]*candidateAccumulator{}
	seenEventIDs := map[string]string{}
	var readBytes int64
	var consumed int64
	for _, file := range files {
		if consumed >= limits.MaxFiles || (opTimeout > 0 && time.Since(started) > opTimeout) {
			batch.Truncated = true
			break
		}
		remaining := limits.MaxBytes - readBytes
		if remaining <= 0 {
			batch.Truncated = true
			break
		}
		data, err := readEventFile(file.path, remaining)
		if errors.Is(err, errBudget) {
			batch.Truncated = true
			break
		}
		if err != nil {
			return protocol.EvidenceBatch{}, fmt.Errorf("%w: event file refused", errInvalidEvent)
		}
		readBytes += int64(len(data))
		consumed++
		event, err := parseEvent(data)
		if err != nil {
			return protocol.EvidenceBatch{}, err
		}
		if file.name != event.EventID+".json" {
			return protocol.EvidenceBatch{}, fmt.Errorf("%w: filename does not match event_id", errInvalidEvent)
		}
		canonical, _ := json.Marshal(event)
		contentSum := sha256.Sum256(canonical)
		contentHash := hex.EncodeToString(contentSum[:])
		if previous, exists := seenEventIDs[event.EventID]; exists {
			if previous != contentHash {
				return protocol.EvidenceBatch{}, fmt.Errorf("%w: conflicting duplicate event_id", errInvalidEvent)
			}
			continue
		}
		seenEventIDs[event.EventID] = contentHash

		candidateKey := strings.Join([]string{
			event.Identity.TenantRef,
			event.Identity.SubjectRef,
			event.Execution.Profile,
			event.Authorization.DataScopeRefSHA256,
			event.Authorization.AuthorizationSnapshotSHA256,
			event.Execution.ModelRouteSHA256,
		}, "\x00")
		candidateSum := sha256.Sum256([]byte(candidateKey))
		candidateID := "siq:" + hex.EncodeToString(candidateSum[:])
		evidenceID := "ev:siq:" + strings.TrimPrefix(event.EventID, "sev_")
		acc := accumulators[candidateKey]
		if acc == nil {
			acc = &candidateAccumulator{
				candidateID: candidateID,
				profile:     event.Execution.Profile,
				tenantRef:   event.Identity.TenantRef,
				subjectRef:  event.Identity.SubjectRef,
				scopeDigest: event.Authorization.DataScopeRefSHA256,
				authDigest:  event.Authorization.AuthorizationSnapshotSHA256,
				modelDigest: event.Execution.ModelRouteSHA256,
				class:       event.Authorization.DataClassification,
				eventTypes:  map[string]bool{},
				statuses:    map[string]bool{},
				observedAt:  event.OccurredAt,
			}
			accumulators[candidateKey] = acc
		}
		acc.evidenceIDs = append(acc.evidenceIDs, evidenceID)
		acc.eventTypes[event.EventType] = true
		acc.statuses[event.Lifecycle.Status] = true
		if event.OccurredAt < acc.observedAt {
			acc.observedAt = event.OccurredAt
		}
		now := time.Now().UTC().Format(time.RFC3339)
		batch.Evidence = append(batch.Evidence, &protocol.Evidence{
			EvidenceID:       evidenceID,
			SourceType:       "gateway",
			SourceLocator:    "siq://business-security-event/" + event.EventID,
			SubjectRef:       stringPtr(candidateID),
			ObservedAt:       event.OccurredAt,
			CollectedAt:      now,
			CollectorID:      "",
			ConnectorVersion: connectorVersion,
			ContentHash:      contentHash,
			RedactionProfile: protocol.RedactionProfile,
			Classification:   evidenceClassification(event.Authorization.DataClassification),
			Signature:        "",
		})
	}

	keys := make([]string, 0, len(accumulators))
	for key := range accumulators {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		acc := accumulators[key]
		sort.Strings(acc.evidenceIDs)
		batch.Candidates = append(batch.Candidates, &protocol.Candidate{
			CandidateID:    acc.candidateID,
			SourceType:     "siq_hub",
			SourceLocator:  "siq://business-agent-binding/" + strings.TrimPrefix(acc.candidateID, "siq:"),
			DiscoveredAt:   acc.observedAt,
			Name:           acc.profile,
			Framework:      "siq-hermes-openshell",
			ArtifactDigest: acc.modelDigest,
			Attributes: map[string]string{
				"schema_version":                eventSchema,
				"tenant_ref":                    acc.tenantRef,
				"subject_ref":                   acc.subjectRef,
				"data_scope_ref_sha256":         acc.scopeDigest,
				"authorization_snapshot_sha256": acc.authDigest,
				"data_classification":           acc.class,
				"event_types":                   sortedSet(acc.eventTypes),
				"lifecycle_statuses":            sortedSet(acc.statuses),
				"event_count":                   strconv.Itoa(len(acc.evidenceIDs)),
			},
			EvidenceIDs: acc.evidenceIDs,
			Confidence:  1,
			Status:      "candidate",
		})
	}
	sort.Slice(batch.Evidence, func(i, j int) bool { return batch.Evidence[i].EvidenceID < batch.Evidence[j].EvidenceID })
	lastCursor = "siq-cursor:" + batchCursor(batch.Evidence)
	batch.Cursor = lastCursor
	return batch, nil
}

func listEventFiles(roots []string) ([]eventFile, error) {
	var files []eventFile
	for _, raw := range roots {
		root := strings.TrimSpace(protocol.ExpandHome(raw))
		entries, err := os.ReadDir(root)
		if err != nil {
			return nil, fmt.Errorf("read SIQ export root: %w", err)
		}
		for _, entry := range entries {
			if strings.HasPrefix(entry.Name(), ".") || !strings.HasSuffix(entry.Name(), ".json") {
				continue
			}
			if entry.Type()&os.ModeSymlink != 0 || entry.IsDir() {
				return nil, fmt.Errorf("%w: symlink or directory event refused", errInvalidEvent)
			}
			files = append(files, eventFile{path: filepath.Join(root, entry.Name()), name: entry.Name()})
		}
	}
	sort.Slice(files, func(i, j int) bool {
		if files[i].name == files[j].name {
			return files[i].path < files[j].path
		}
		return files[i].name < files[j].name
	})
	return files, nil
}

func readEventFile(path string, maxBytes int64) ([]byte, error) {
	if maxBytes <= 0 {
		return nil, errBudget
	}
	file, err := openRegular(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return nil, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 {
		return nil, fmt.Errorf("event must be an owner-only regular file")
	}
	if err := validatePrivateOwner(info); err != nil {
		return nil, err
	}
	if err := validateSingleLink(info); err != nil {
		return nil, err
	}
	data, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > maxBytes {
		return nil, errBudget
	}
	return data, nil
}

func parseEvent(data []byte) (businessSecurityEvent, error) {
	var event businessSecurityEvent
	if len(data) == 0 || len(data) > 64*1024 {
		return event, fmt.Errorf("%w: invalid event size", errInvalidEvent)
	}
	if err := rejectDuplicateKeys(data); err != nil {
		return event, fmt.Errorf("%w: duplicate or malformed JSON", errInvalidEvent)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&event); err != nil {
		return event, fmt.Errorf("%w: schema fields invalid", errInvalidEvent)
	}
	if err := ensureJSONEOF(decoder); err != nil {
		return event, fmt.Errorf("%w: trailing JSON data", errInvalidEvent)
	}
	if err := validateEvent(event); err != nil {
		return event, err
	}
	return event, nil
}

func validateEvent(event businessSecurityEvent) error {
	invalid := func(reason string) error { return fmt.Errorf("%w: %s", errInvalidEvent, reason) }
	if event.SchemaVersion != eventSchema || event.Producer != eventProducer {
		return invalid("unsupported producer or schema")
	}
	if !eventIDRE.MatchString(event.EventID) {
		return invalid("event_id invalid")
	}
	if _, err := time.Parse(time.RFC3339, event.OccurredAt); err != nil {
		return invalid("occurred_at invalid")
	}
	for _, ref := range []string{
		event.Identity.TenantRef,
		event.Identity.SubjectRef,
		event.Authorization.ScopeTenantRef,
		event.Execution.RunRef,
		event.Execution.SessionRef,
		event.Execution.SandboxRef,
		event.Audit.CorrelationRef,
	} {
		if !hashRefRE.MatchString(ref) {
			return invalid("hashed reference invalid")
		}
	}
	if event.Audit.AuditTraceRef != nil && !hashRefRE.MatchString(*event.Audit.AuditTraceRef) {
		return invalid("audit trace reference invalid")
	}
	for _, digest := range []string{
		event.Authorization.DataScopeRefSHA256,
		event.Authorization.AuthorizationSnapshotSHA256,
		event.Execution.ModelRouteSHA256,
	} {
		if !digestRE.MatchString(digest) {
			return invalid("digest invalid")
		}
	}
	if event.Identity.TenantRef != event.Authorization.ScopeTenantRef {
		return invalid("identity tenant and authorized scope tenant differ")
	}
	if event.Execution.RunRef != event.Audit.CorrelationRef {
		return invalid("run and audit correlation differ")
	}
	if !profileRE.MatchString(event.Execution.Profile) || event.Execution.RuntimeTarget != "openshell" {
		return invalid("execution identity invalid")
	}
	if event.Authorization.DataClassification != "public_research" && event.Authorization.DataClassification != "confidential_local" {
		return invalid("data classification invalid")
	}
	quiesced := event.Lifecycle.RuntimeTerminalConfirmed && event.Lifecycle.ChildrenTerminalConfirmed
	if event.Lifecycle.WriteQuiesced != quiesced {
		return invalid("write quiescence does not match terminal confirmations")
	}
	if event.EventType == "agent_run.admitted" {
		if event.Lifecycle.Status != "admitted" || event.Lifecycle.RuntimeTerminalConfirmed ||
			event.Lifecycle.ChildrenTerminalConfirmed || event.Lifecycle.WriteQuiesced {
			return invalid("admission lifecycle invalid")
		}
		return nil
	}
	if event.EventType != "agent_run.terminal" || event.Lifecycle.Status == "admitted" {
		return invalid("terminal lifecycle invalid")
	}
	terminalStatuses := map[string]bool{
		"succeeded": true, "completed": true, "failed": true, "cancelled": true,
		"timed_out": true, "protocol_eof": true, "orphaned": true,
	}
	if !terminalStatuses[event.Lifecycle.Status] {
		return invalid("terminal status invalid")
	}
	if (event.Lifecycle.Status == "succeeded" || event.Lifecycle.Status == "completed") && !quiesced {
		return invalid("successful terminal event is not write-quiesced")
	}
	return nil
}

func rejectDuplicateKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	first, err := decoder.Token()
	if err != nil {
		return err
	}
	if err := consumeJSONToken(decoder, first); err != nil {
		return err
	}
	return ensureJSONEOF(decoder)
}

func consumeJSONToken(decoder *json.Decoder, token json.Token) error {
	delimiter, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		seen := map[string]bool{}
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok || seen[key] {
				return errors.New("duplicate or non-string object key")
			}
			seen[key] = true
			valueToken, err := decoder.Token()
			if err != nil {
				return err
			}
			if err := consumeJSONToken(decoder, valueToken); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil || closing != json.Delim('}') {
			return errors.New("object not closed")
		}
	case '[':
		for decoder.More() {
			valueToken, err := decoder.Token()
			if err != nil {
				return err
			}
			if err := consumeJSONToken(decoder, valueToken); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil || closing != json.Delim(']') {
			return errors.New("array not closed")
		}
	default:
		return errors.New("unexpected JSON delimiter")
	}
	return nil
}

func ensureJSONEOF(decoder *json.Decoder) error {
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("multiple JSON values")
		}
		return err
	}
	return nil
}

func sortedSet(values map[string]bool) string {
	out := make([]string, 0, len(values))
	for value := range values {
		out = append(out, value)
	}
	sort.Strings(out)
	return strings.Join(out, ",")
}

func evidenceClassification(classification string) string {
	if classification == "confidential_local" {
		return "confidential"
	}
	return "public"
}

func batchCursor(evidence []*protocol.Evidence) string {
	hash := sha256.New()
	for _, item := range evidence {
		hash.Write([]byte(item.EvidenceID))
		hash.Write([]byte{0})
		hash.Write([]byte(item.ContentHash))
		hash.Write([]byte{0})
	}
	return hex.EncodeToString(hash.Sum(nil))
}

func stringPtr(value string) *string { return &value }

func toProtocolError(err error) *protocol.ProtocolError {
	switch {
	case errors.Is(err, errScope):
		return &protocol.ProtocolError{Code: protocol.CodeScopeInvalid, Message: "SIQ security export scope invalid"}
	case errors.Is(err, errBudget):
		return &protocol.ProtocolError{Code: protocol.CodeLimitExceeded, Message: "SIQ security export byte limit exceeded"}
	case errors.Is(err, errInvalidEvent):
		return &protocol.ProtocolError{Code: protocol.CodeRedactionFailure, Message: "SIQ security event rejected"}
	default:
		return &protocol.ProtocolError{Code: "internal_error", Message: "SIQ security event collection failed"}
	}
}
