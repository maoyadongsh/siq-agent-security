package adapterinstall

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

// Reuse only a first snapshot pinned by the authenticated, committed uninstall
// of this exact Windows profile. This grants no ownership over the changed live
// fields: normal installation/uninstallation still edits only product hooks.
func (p *Plan) workBuddyReinstallSnapshot(path, original string, snapshot fileImage) bool {
	o := p.payload.Options
	if runtime.GOOS != "windows" || o.Platform != WorkBuddy || path != filepath.Join(o.configRoot(), "settings.json") || original != path+originalSuffix {
		return false
	}
	st := &state.Store{Dir: o.StateDir}
	rev, raw, err := st.LatestSeq("adapter-operations", operationKey(o))
	if err != nil || rev < 0 {
		return false
	}
	var claim operationClaim
	if json.Unmarshal(raw, &claim) != nil || claim.Schema != "adapter-operation/v1" || claim.Platform != WorkBuddy || claim.Action != "uninstall" {
		return false
	}
	status, err := endState(o.StateDir, claim)
	if err != nil || status != "committed" {
		return false
	}
	prior, err := unsealPlan(o.StateDir, claim)
	if err != nil || !workBuddyRecoveryMatches(prior, o) || prior.payload.Record.Modified[path] != original {
		return false
	}
	pinned, ok := prior.payload.Inputs[original]
	return ok && pinned.Exists && snapshot.Exists && bytes.Equal(pinned.Data, snapshot.Data)
}

func WithWorkBuddyInstance(opts Options, root string) Options {
	opts.Instance = &InstanceTarget{ID: hermeshome.Identifier(root), Name: "default", ConfigDir: root}
	return opts
}

func workBuddyManagedConfigPath(o Options) string {
	return filepath.Join(o.configRoot(), product.Name+".json")
}

// WorkBuddyManagedConfigReference detects the file and recorded managed
// installations with a removed file. Neither may fall back to shared tokens.
func WorkBuddyManagedConfigReference(home, stateDir string) (string, bool, error) {
	o := Options{Platform: WorkBuddy, Home: home, StateDir: stateDir}
	if err := validateWorkBuddyConfigDir(); err != nil {
		return "", false, err
	}
	path := workBuddyManagedConfigPath(o)
	if _, err := os.Lstat(path); err == nil {
		return path, true, nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return path, true, err
	}
	record, err := newestInstanceRecord(o)
	if err != nil && !errors.Is(err, errNoInstallRecord) {
		return path, false, err
	}
	return path, record != nil && record.RuntimeIdentityID != "", nil
}

func workBuddyManagedCommand(binary string, o Options) string {
	return hookCommand(binary, WorkBuddy, o.StateDir) + " --managed-config " + hookArg(workBuddyManagedConfigPath(o))
}

func (p *Plan) prepareWorkBuddyManagedConfig() error {
	o := p.payload.Options
	path := workBuddyManagedConfigPath(o)
	previous, err := p.input(path)
	if err != nil {
		return err
	}
	if o.RuntimeIdentityID == "" {
		if previous.Exists {
			return ErrPlanChanged
		}
		return nil
	}
	if !filepath.IsAbs(o.StateDir) || filepath.Clean(o.StateDir) != o.StateDir {
		return ErrPlanChanged
	}
	if previous.Exists && !p.owns(path) {
		return ErrPlanChanged
	}
	if err := p.pinRuntimeIdentity(); err != nil {
		return err
	}
	cfg := adapters.WorkBuddyManagedConfig{SchemaVersion: "workbuddy-managed-hook/v1", RuntimeIdentityID: o.RuntimeIdentityID,
		InstanceID: o.Instance.ID, AgentID: "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-"), CredentialPath: managedCredentialPath(o), Endpoint: o.Endpoint, EnforcementMode: o.Mode, StateDir: o.StateDir}
	raw, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	if _, err := adapters.DecodeWorkBuddyManagedConfig(raw, path, o.StateDir); err != nil {
		return ErrPlanChanged
	}
	if err := adapters.PreviewWorkBuddyManagedConfig(raw, path, o.StateDir); err != nil {
		return err
	}
	return p.write(path, append(raw, '\n'), 0600, "连接已确认的 WorkBuddy 实例身份；仅保存专属凭据引用")
}

// Recheck live private-object facts even on an otherwise idempotent request.
// Secret bytes are deliberately absent from the reviewed and sealed plan.
func (p *Plan) checkWorkBuddyPreflight(readback bool) error {
	o := p.payload.Options
	if o.Platform != WorkBuddy || o.RuntimeIdentityID == "" || p.payload.View.Action != "install" {
		return nil
	}
	path := workBuddyManagedConfigPath(o)
	if readback {
		cfg, err := adapters.InspectWorkBuddyManagedConfig(path, o.StateDir)
		if err != nil {
			return err
		}
		if cfg.RuntimeIdentityID != o.RuntimeIdentityID || cfg.Endpoint != o.Endpoint || cfg.EnforcementMode != o.Mode {
			return ErrPlanChanged
		}
		return nil
	}
	raw := p.payload.Inputs[path].Data
	for _, op := range p.payload.Files {
		if op.Path == path {
			raw = op.After.Data
		}
	}
	return adapters.PreviewWorkBuddyManagedConfig(raw, path, o.StateDir)
}

func upsertWorkBuddyManagedHook(existing any, command string, o Options, recordedBinary string) []any {
	list, _ := existing.([]any)
	kept := make([]any, 0, len(list)+1)
	for _, item := range list {
		group, _ := item.(map[string]any)
		hooks, _ := group["hooks"].([]any)
		remaining := make([]any, 0, len(hooks))
		removed := false
		for _, value := range hooks {
			hook, _ := value.(map[string]any)
			text, _ := hook["command"].(string)
			owned := text == command || recordedBinary != "" && (text == workBuddyManagedCommand(recordedBinary, o) || isRecordedToolHook(text, WorkBuddy, recordedBinary, o.StateDir))
			if hook["type"] == "command" && owned {
				removed = true
				continue
			}
			remaining = append(remaining, value)
		}
		if !removed {
			kept = append(kept, item)
		} else if len(remaining) != 0 {
			// Keep the user's matcher and metadata: broadening a mixed group
			// would also change when unrelated user hooks execute.
			copy := make(map[string]any, len(group))
			for key, value := range group {
				copy[key] = value
			}
			copy["hooks"] = remaining
			kept = append(kept, copy)
		}
	}
	// Rebuild exactly one owned synchronous hook. Reusing its old group can
	// preserve a restricted matcher or async execution and defeat repair.
	return append(kept, map[string]any{"matcher": ".*", "hooks": []any{
		map[string]any{"type": "command", "command": command, "timeout": 75},
	}})
}

func workBuddyManagedConnectionMatches(o Options, raw []byte) bool {
	cfg, err := adapters.DecodeWorkBuddyManagedConfig(raw, workBuddyManagedConfigPath(o), o.StateDir)
	return err == nil && (o.RuntimeIdentityID == "" || cfg.RuntimeIdentityID == o.RuntimeIdentityID) && cfg.Endpoint == o.Endpoint && cfg.EnforcementMode == o.Mode
}

func inspectWorkBuddyManaged(d *Diagnosis, o Options) bool {
	path := workBuddyManagedConfigPath(o)
	_, statErr := os.Lstat(path)
	if errors.Is(statErr, os.ErrNotExist) && o.RuntimeIdentityID == "" {
		rec, err := newestInstanceRecord(o)
		if (errors.Is(err, errNoInstallRecord) || err == nil) && (rec == nil || rec.RuntimeIdentityID == "") {
			return false
		}
	}
	cfg, err := adapters.InspectWorkBuddyManagedConfig(path, o.StateDir)
	if err == nil && (o.RuntimeIdentityID == "" || cfg.RuntimeIdentityID == o.RuntimeIdentityID) && cfg.Endpoint == o.Endpoint && cfg.EnforcementMode == o.Mode {
		d.check("service_configuration", "pass", "受管配置、直接父目录及凭据对象通过当前私密校验；未读取凭据内容，身份有效性和原生运行仍待验证")
	} else {
		d.check("service_configuration", "fail", "WorkBuddy 受管配置缺失或不一致；禁止回退共享凭据，请重新预览修复")
		var failure *adapters.WorkBuddyPreflightError
		if errors.As(err, &failure) {
			d.check(failure.Code, "fail", "受管运行前置检查失败；请检查对应专用对象后重新预览，未自动修改权限")
			if failure.ObjectCode != "" {
				d.check(failure.ReasonCode(), "fail", "私密对象检查类别；未读取凭据内容、未修改 ACL")
			}
		}
	}
	doc, err := inspectJSON(o.Home, filepath.Join(o.configRoot(), "settings.json"))
	if err == nil && hostHookRegisteredCommand(doc, workBuddyManagedCommand(o.Binary, o)) {
		d.check("host_registration", "pass", "前置和后置钩子已固定受管配置路径；尚需桌面验证")
	} else {
		d.check("host_registration", "fail", "受管钩子命令缺失或未固定当前配置")
	}
	d.check("approval_resumption", "unknown", "已配置原 hold 关联与唯一预留恢复链；实际桌面审批、重试和后置观察仍待核验，宿主 ask 不代表 SIQ 批准")
	return true
}
