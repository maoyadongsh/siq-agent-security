package adapterinstall

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"slices"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/state"
)

type PlannedChange struct {
	Path         string `json:"path"`
	Action       string `json:"action"`
	Purpose      string `json:"purpose"`
	BeforeSHA256 string `json:"before_sha256"`
	AfterSHA256  string `json:"after_sha256"`
}

type PlanView struct {
	RuntimeIdentityID string          `json:"runtime_identity_id,omitempty"`
	InstanceID        string          `json:"instance_id,omitempty"`
	InstanceName      string          `json:"instance_name,omitempty"`
	NativeEnable      *bool           `json:"native_enable,omitempty"`
	SchemaVersion     string          `json:"schema_version"`
	PlanID            string          `json:"plan_id"`
	PlanDigest        string          `json:"plan_digest"`
	Platform          string          `json:"platform"`
	Action            string          `json:"action"`
	ExpiresAt         string          `json:"expires_at"`
	Changes           []PlannedChange `json:"changes"`
	NextSteps         []string        `json:"next_steps"`
	RestartRequired   bool            `json:"restart_required"`
	RuntimeVerified   bool            `json:"runtime_verified"`
}

type fileImage struct {
	Exists bool   `json:"exists"`
	Data   []byte `json:"data,omitempty"`
	Mode   uint32 `json:"mode"`
}
type fileChange struct {
	Path   string    `json:"path"`
	Before fileImage `json:"before"`
	After  fileImage `json:"after"`
}
type planPayload struct {
	NativeCLIDigest  string               `json:"native_cli_digest,omitempty"`
	View             PlanView             `json:"view"`
	Options          Options              `json:"options"`
	ExpectedRevision int                  `json:"expected_revision"`
	Record           Record               `json:"record"`
	Files            []fileChange         `json:"files"`
	BinaryDigest     string               `json:"binary_digest,omitempty"`
	Inputs           map[string]fileImage `json:"inputs"`
}

// Plan contains private configuration material. Only View may be serialized
// into an HTTP response or CLI output. Durable recovery material is encrypted.
type Plan struct {
	payload      planPayload
	instanceRoot os.FileInfo // Process-local preview binding, never recovery material.
}

func (p *Plan) View() PlanView { return p.payload.View }

var ErrPlanChanged = errors.New("adapter: configuration changed; preview again")
var ErrRecoveryRequired = errors.New("adapter: unfinished operation requires recovery")

func imageHash(image fileImage) string {
	if !image.Exists {
		return ""
	}
	sum := sha256.Sum256(image.Data)
	return hex.EncodeToString(sum[:])
}
func sameImage(a, b fileImage) bool {
	return a.Exists == b.Exists && (!a.Exists || (runtime.GOOS == "windows" || a.Mode == b.Mode) && bytes.Equal(a.Data, b.Data))
}

// Read an existing regular file or an explicitly missing file. Missing leaf
// paths still require every existing ancestor to be a real directory.
func readImage(home, path string) (fileImage, error) {
	if !filepath.IsAbs(path) {
		return fileImage{}, errors.New("adapter: absolute path required")
	}
	for current := filepath.Clean(path); ; current = filepath.Dir(current) {
		info, err := os.Lstat(current)
		if err != nil && !os.IsNotExist(err) {
			return fileImage{}, errors.New("adapter: file inspection failed")
		}
		if err == nil {
			leaf := current == filepath.Clean(path)
			if leaf && info.Mode()&os.ModeSymlink != 0 {
				return fileImage{}, errors.New("adapter: symlink or invalid ancestor refused")
			}
			if !leaf && !stateformat.AcceptDirectory(info, current) {
				return fileImage{}, errors.New("adapter: symlink or invalid ancestor refused")
			}
		}
		if current == filepath.Clean(home) || filepath.Dir(current) == current {
			break
		}
	}
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return fileImage{}, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Size() > 1<<20 {
		return fileImage{}, errors.New("adapter: file type or size refused")
	}
	raw, err := inspectRead(home, path)
	if err != nil {
		return fileImage{}, err
	}
	return fileImage{Exists: true, Data: raw, Mode: uint32(info.Mode().Perm())}, nil
}

// input pins the first read, including files whose planned output is unchanged.
// All transformations and recovery copies use this same reviewed baseline.
func (p *Plan) input(path string) (fileImage, error) {
	if image, ok := p.payload.Inputs[path]; ok {
		return image, nil
	}
	image, err := readImage(p.payload.Options.Home, path)
	if err != nil {
		return fileImage{}, err
	}
	if len(p.payload.Inputs) >= 64 {
		return fileImage{}, errors.New("adapter: input budget exceeded")
	}
	p.payload.Inputs[path] = image
	return image, nil
}

func (p *Plan) add(path string, after fileImage, purpose string) error {
	if len(after.Data) > 1<<20 {
		return errors.New("adapter: output budget exceeded")
	}
	before, err := p.input(path)
	if err != nil {
		return err
	}
	if sameImage(before, after) {
		return nil
	}
	for _, op := range p.payload.Files {
		if op.Path == path {
			return errors.New("adapter: duplicate planned path")
		}
	}
	if len(p.payload.Files) >= 32 {
		return errors.New("adapter: change budget exceeded")
	}
	action := "replace"
	if !before.Exists {
		action = "create"
	}
	if !after.Exists {
		action = "remove"
	}
	shown := filepath.ToSlash(path)
	home := strings.TrimSuffix(filepath.ToSlash(p.payload.Options.Home), "/")
	if strings.HasPrefix(shown, home+"/") {
		shown = "~" + strings.TrimPrefix(shown, home)
	}
	p.payload.Files = append(p.payload.Files, fileChange{Path: path, Before: before, After: after})
	p.payload.View.Changes = append(p.payload.View.Changes, PlannedChange{Path: shown, Action: action, Purpose: purpose, BeforeSHA256: imageHash(before), AfterSHA256: imageHash(after)})
	return nil
}

func (p *Plan) write(path string, raw []byte, mode uint32, purpose string) error {
	rec := &p.payload.Record
	before, err := p.input(path)
	if err != nil {
		return err
	}
	created := false
	for _, own := range rec.Created {
		created = created || own == path
	}
	if !before.Exists || created {
		rec.Created = appendUnique(rec.Created, path)
	} else if rec.Modified[path] == "" {
		original := path + originalSuffix
		snapshot, err := p.input(original)
		if err != nil {
			return err
		}
		if snapshot.Exists && !bytes.Equal(snapshot.Data, before.Data) && !jsonDocumentsEqual(snapshot.Data, before.Data) {
			return errors.New("adapter: existing original snapshot needs review")
		}
		if !snapshot.Exists {
			if err := p.add(original, fileImage{Exists: true, Data: before.Data, Mode: 0o600}, "保留首次接入前的不可变恢复副本"); err != nil {
				return err
			}
		}
		rec.Modified[path] = original
		rec.OriginalModes[path] = before.Mode
	}
	after := fileImage{Exists: true, Data: raw, Mode: mode}
	rec.Written[path] = imageHash(after)
	return p.add(path, after, purpose)
}

func (p *Plan) planJSON(path string) (map[string]any, error) {
	image, err := p.input(path)
	if err != nil {
		return nil, err
	}
	if !image.Exists || len(bytes.TrimSpace(image.Data)) == 0 {
		return map[string]any{}, nil
	}
	var doc map[string]any
	if json.Unmarshal(image.Data, &doc) != nil || doc == nil {
		return nil, errors.New("adapter: invalid JSON configuration")
	}
	return doc, nil
}

func encodePlanJSON(doc map[string]any) []byte {
	raw, _ := json.MarshalIndent(doc, "", "  ")
	return append(raw, '\n')
}

func jsonDocumentsEqual(a, b []byte) bool {
	var da, db any
	if json.Unmarshal(a, &da) != nil || json.Unmarshal(b, &db) != nil {
		return false
	}
	return reflect.DeepEqual(da, db)
}

func Prepare(opts Options, action string) (*Plan, error) {
	if err := opts.normalise(); err != nil {
		return nil, err
	}
	if action != "install" && action != "uninstall" {
		return nil, errors.New("adapter: invalid action")
	}
	binaryDigest := ""
	if action == "install" && opts.Platform != Trae {
		var err error
		binaryDigest, err = programDigest(opts.Binary)
		if err != nil {
			return nil, err
		}
	}
	if err := validateTransactionStore(opts.StateDir); err != nil {
		return nil, err
	}
	st := &state.Store{Dir: opts.StateDir}
	rev, _, err := st.LatestSeq("adapter-operations", operationKey(opts))
	if err != nil {
		return nil, err
	}
	prior, err := newestInstanceRecord(opts)
	if err != nil && !errors.Is(err, errNoInstallRecord) {
		return nil, err
	}
	err = nil
	if action == "uninstall" && prior == nil && opts.Platform != Trae {
		return nil, errNoInstallRecord
	}
	if prior != nil && (opts.Platform == CodeBuddy || opts.Platform == WorkBuddy) {
		path := filepath.Join(opts.configRoot(), "settings.json")
		if prior.Modified[path] == "" && prior.Written[path] == "" && !slices.Contains(prior.Created, path) {
			return nil, errors.New("adapter: host config directory differs from latest install record")
		}
	}
	if prior != nil && prior.RuntimeIdentityID != "" {
		if action == "uninstall" && opts.RuntimeIdentityID != "" && opts.RuntimeIdentityID != prior.RuntimeIdentityID {
			return nil, ErrPlanChanged
		}
		if opts.RuntimeIdentityID == "" {
			opts.RuntimeIdentityID = prior.RuntimeIdentityID
		}
	}
	if opts.RuntimeIdentityID != "" && !validManagedTarget(opts) {
		return nil, ErrPlanChanged
	}
	var id [16]byte
	if _, err := rand.Read(id[:]); err != nil {
		return nil, err
	}
	view := PlanView{SchemaVersion: "local-adapter-plan/v1", PlanID: "ap-" + hex.EncodeToString(id[:]), Platform: opts.Platform, Action: action,
		ExpiresAt: time.Now().UTC().Add(5 * time.Minute).Format(time.RFC3339), Changes: []PlannedChange{}, NextSteps: []string{}, RestartRequired: opts.Platform != Trae}
	rec := Record{Platform: opts.Platform, InstalledAt: opts.Now.UTC().Format(time.RFC3339), Binary: opts.Binary, Created: []string{}, Modified: map[string]string{}, Written: map[string]string{}, OriginalModes: map[string]uint32{}}
	if prior != nil {
		raw, _ := json.Marshal(prior)
		_ = json.Unmarshal(raw, &rec)
		if rec.Modified == nil {
			rec.Modified = map[string]string{}
		}
		if rec.Written == nil {
			rec.Written = map[string]string{}
		}
		if rec.OriginalModes == nil {
			rec.OriginalModes = map[string]uint32{}
		}
	}
	if opts.Instance != nil {
		view.SchemaVersion = "local-adapter-plan/v2"
		view.InstanceID = opts.Instance.ID
		view.InstanceName = opts.Instance.Name
		enabled := opts.NativeEnable
		view.NativeEnable = &enabled
		rec.InstanceID = opts.Instance.ID
		rec.ConfigDir = opts.Instance.ConfigDir
	}
	if opts.RuntimeIdentityID != "" {
		view.SchemaVersion = "local-adapter-plan/v3"
		view.RuntimeIdentityID = opts.RuntimeIdentityID
		rec.RuntimeIdentityID = opts.RuntimeIdentityID
		if action == "uninstall" {
			view.NextSteps = append(view.NextSteps, "确认卸载将先停用实例授权；配置移除失败时授权仍保持停用，不会恢复旧凭据。")
		}
	}
	p := &Plan{payload: planPayload{View: view, Options: opts, ExpectedRevision: rev, Record: rec, Files: []fileChange{}, Inputs: map[string]fileImage{}, BinaryDigest: binaryDigest}}
	if opts.Instance != nil {
		p.instanceRoot, err = inspectInstanceRoot(opts.Instance)
		if err != nil {
			return nil, err
		}
	}
	if opts.Platform == Trae {
		p.payload.View.NextSteps = append(p.payload.View.NextSteps, "当前平台没有工具钩子，可继续静态检查与盘点。")
	} else if action == "install" {
		err = p.prepareInstall()
	} else {
		err = p.prepareUninstall()
	}
	if err != nil {
		return nil, err
	}
	if action == "install" {
		p.payload.Record.Binary = opts.Binary
		p.payload.Record.InstalledAt = opts.Now.UTC().Format(time.RFC3339)
	}
	if opts.Platform == Hermes && action == "install" && !opts.NativeEnable {
		p.payload.View.NextSteps = append(p.payload.View.NextSteps, "仍需在目标 Hermes profile 启用插件；本次不自动重启会话。")
	}
	if action == "install" {
		p.payload.View.NextSteps = append(p.payload.View.NextSteps, installEntryStep(opts))
	}
	p.payload.View.NextSteps = append(p.payload.View.NextSteps, "配置应用后检查诊断，并在方便时重启目标会话、验证实际调用；此操作不产生运行验证结论。")
	if err := p.verifyInstanceRoot(); err != nil {
		return nil, err
	}
	digest, err := p.digest()
	if err != nil {
		return nil, err
	}
	p.payload.View.PlanDigest = digest
	return p, nil
}

func (p *Plan) digest() (string, error) {
	payload := p.payload
	payload.View.PlanDigest = ""
	encoded, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.UseNumber()
	var document any
	if err := decoder.Decode(&document); err != nil {
		return "", err
	}
	raw, err := canon.Marshal(document)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

func (p *Plan) prepareInstall() error {
	o := p.payload.Options
	root := o.configRoot()
	plugin := filepath.Join(root, "plugins", product.PluginDir())
	if o.Platform == Hermes || o.Platform == OpenClaw {
		assets := []string{"plugin.yaml", "__init__.py"}
		if o.Platform == OpenClaw {
			assets = []string{"package.json", "index.ts", "openclaw.plugin.json"}
		}
		for _, name := range assets {
			raw, err := p.asset(o.Platform + "/" + name)
			if err != nil {
				return err
			}
			if err := p.write(filepath.Join(plugin, name), raw, 0o600, "安装当前版本的工具调用适配器文件"); err != nil {
				return err
			}
		}
		path := filepath.Join(plugin, "config.json")
		cfg := map[string]any{"endpoint": o.Endpoint, "token_path": filepath.Join(o.StateDir, "token"), "enforcement_mode": o.Mode, "timeout_s": 5}
		if o.Platform == Hermes {
			previous, err := p.planJSON(path)
			if err != nil {
				return err
			}
			if _, managed := previous["runtime_identity_id"]; managed && o.RuntimeIdentityID == "" {
				return ErrPlanChanged
			}
			if o.RuntimeIdentityID != "" {
				if err := p.pinRuntimeIdentity(); err != nil {
					return err
				}
				cfg["runtime_identity_id"] = o.RuntimeIdentityID
				cfg["agent_id"] = "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-")
				cfg["token_path"] = managedCredentialPath(o)
			}
		}
		if o.Platform == OpenClaw {
			path = filepath.Join(root, product.Name+".json")
			cfg = map[string]any{"endpoint": o.Endpoint, "tokenPath": filepath.Join(o.StateDir, "token"), "enforcementMode": o.Mode, "timeoutMs": 5000}
			previous, err := p.planJSON(path)
			if err != nil {
				return err
			}
			if _, managed := previous["runtimeIdentityId"]; managed && o.RuntimeIdentityID == "" {
				return ErrPlanChanged
			}
			if o.RuntimeIdentityID != "" {
				if err := p.pinRuntimeIdentity(); err != nil {
					return err
				}
				cfg["runtimeIdentityId"] = o.RuntimeIdentityID
				cfg["agentId"] = "hri-" + strings.TrimPrefix(o.Instance.ID, "hi-")
				cfg["tokenPath"] = managedCredentialPath(o)
			}
		}
		if err := p.write(path, encodePlanJSON(cfg), 0o600, "连接当前本地服务，使用决策凭据引用和当前执行模式"); err != nil {
			return err
		}
	}
	switch o.Platform {
	case Hermes:
		if o.NativeEnable {
			if err := p.prepareHermesNative(false); err != nil {
				return err
			}
		}
		if runtime.GOOS != "windows" {
			return p.write(o.wrapperPath(), hermesWrapper(o), 0o700, "安装先检查后调用 Hermes 的 Skill 安装入口")
		}
	case OpenClaw:
		path := filepath.Join(root, "openclaw.json")
		doc, err := p.planJSON(path)
		if err != nil {
			return err
		}
		if err := configureOpenClawRuntime(doc, plugin); err != nil {
			return err
		}
		sec, ok := doc["security"].(map[string]any)
		if _, exists := doc["security"]; exists && !ok {
			return errors.New("adapter: invalid OpenClaw security object")
		}
		if previous, exists := sec["installPolicy"]; exists {
			// Only migrate the exact legacy policy owned by our install record.
			// Public OpenClaw rejects this key; it is not an installation hook.
			if p.owns(path) && sameOpenClawLegacyPolicy(previous, p.payload.Record.Binary) {
				original, err := p.originalJSON(path)
				if err != nil {
					return err
				}
				oldSec, _ := original["security"].(map[string]any)
				if !reflect.DeepEqual(previous, oldSec["installPolicy"]) {
					delete(sec, "installPolicy")
					if old, exists := oldSec["installPolicy"]; exists {
						sec["installPolicy"] = old
					}
					if len(sec) == 0 {
						delete(doc, "security")
					}
				}
			}
		}
		return p.write(path, encodePlanJSON(doc), 0o600, "登记本插件的加载路径与启用项；保留其他平台设置")
	case CodeBuddy, WorkBuddy:
		path := filepath.Join(root, "settings.json")
		doc, err := p.planJSON(path)
		if err != nil {
			return err
		}
		hooks, ok := doc["hooks"].(map[string]any)
		if _, exists := doc["hooks"]; exists && !ok {
			return errors.New("adapter: invalid host hooks object")
		}
		if hooks == nil {
			hooks = map[string]any{}
		}
		command := hookCommand(o.Binary, o.Platform, o.StateDir)
		for _, event := range []string{"PreToolUse", "PostToolUse"} {
			if v, exists := hooks[event]; exists {
				if _, ok := v.([]any); !ok {
					return errors.New("adapter: invalid host hook list")
				}
			}
			hooks[event] = upsertHook(hooks[event], command, o.Platform)
		}
		doc["hooks"] = hooks
		purpose := "登记工具执行前和执行后的 SIQ 钩子；保留其他设置"
		if o.Platform == WorkBuddy {
			purpose = "登记 WorkBuddy 桌面工具钩子；保留 enabledPlugins 及其他设置，不沿用 CodeBuddy 安装"
		}
		return p.write(path, encodePlanJSON(doc), 0o600, purpose)
	}
	return nil
}

func openClawInstallPolicy(o Options) map[string]any {
	return map[string]any{"enabled": true, "targets": []any{"skill", "plugin"}, "exec": map[string]any{"source": "exec", "command": o.Binary, "args": []any{"policy-exec"}, "timeoutMs": 10000, "trustedDirs": []any{filepath.Dir(o.Binary)}, "passEnv": []any{product.EnvStateDir, product.EnvStateDirOld, "HOME", "PATH"}}}
}

func sameOpenClawLegacyPolicy(value any, binary string) bool {
	// Compare JSON-normalized numbers, since planJSON decodes numbers as float64.
	var expected any
	_ = json.Unmarshal(encodePlanJSON(openClawInstallPolicy(Options{Binary: binary})), &expected)
	return binary != "" && reflect.DeepEqual(value, expected)
}

// shownPath renders paths under the user's home with a "~" prefix, matching
// how planned change paths are displayed, so previews stay stable across
// machines and never leak absolute home paths.
func (o Options) shownPath(path string) string {
	home := filepath.ToSlash(o.Home)
	shown := filepath.ToSlash(path)
	if home != "" && strings.HasPrefix(shown, strings.TrimSuffix(home, "/")+"/") {
		return "~" + strings.TrimPrefix(shown, strings.TrimSuffix(home, "/"))
	}
	return shown
}

// installEntryStep states the install-entry boundary in every reviewed
// preview: the platform's own install entry is only ever taken over when a
// real pre-install interception exists, which no supported platform provides
// today. Until then the reviewed view names either the controlled install
// path (Hermes wrapper, which checks before invoking the native installer) or
// the post-hoc discovery/diagnosis route, and never claims host-wide
// protection from an install action.
func installEntryStep(o Options) string {
	switch o.Platform {
	case Hermes:
		if runtime.GOOS != "windows" {
			return "平台安装入口未被接管；需要先检查后安装时使用受控安装命令 " + o.shownPath(o.wrapperPath()) + "，原生命令不经过检查。"
		}
		return "平台安装入口未被接管，Windows 暂无受控安装命令；通过发现与诊断做事后检查。"
	case Trae:
		return "平台没有工具钩子，安装入口未被接管；通过静态检查、盘点与诊断做事后检查。"
	default:
		return "平台安装入口未被接管，也不注入其不支持的安装拦截配置；通过发现与诊断做事后检查。"
	}
}

func hermesWrapper(o Options) []byte {
	// Shell single quotes are required: Go %q leaves $() and backticks active.
	quote := func(s string) string { return "'" + strings.ReplaceAll(s, "'", "'\"'\"'") + "'" }
	profileEnv := ""
	if o.Instance != nil {
		profileEnv = "export HERMES_HOME=" + quote(o.configRoot()) + "\n"
	}
	return []byte(fmt.Sprintf("#!/bin/sh\nset -eu\nBIN=%s\nexport %s=%s\n%sif [ $# -lt 1 ]; then\n  echo 'usage: hermes-skills-install <skill-src> [hermes skills install args...]' >&2\n  exit 2\nfi\nSRC=$1\nshift\nset +e\n\"$BIN\" admit \"$SRC\"\nstatus=$?\nset -e\nif [ \"$status\" -ne 0 ]; then\n  echo 'siq-agent-security: Skill check failed; install refused' >&2\n  exit \"$status\"\nfi\nexec hermes skills install \"$SRC\" \"$@\"\n", quote(o.Binary), product.EnvStateDir, quote(o.StateDir), profileEnv))
}

func programDigest(path string) (string, error) {
	info, err := os.Lstat(path)
	if !filepath.IsAbs(path) || err != nil || !info.Mode().IsRegular() || info.Size() > 256<<20 {
		return "", errors.New("adapter: program path unavailable")
	}
	f, err := statefs.Open(path)
	if err != nil {
		return "", errors.New("adapter: program unreadable")
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, io.LimitReader(f, (256<<20)+1))
	if err != nil || n > 256<<20 {
		return "", errors.New("adapter: program read limit")
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func (p *Plan) asset(rel string) ([]byte, error) {
	o := p.payload.Options
	parts := strings.SplitN(rel, "/", 2)
	if o.From != "" && len(parts) == 2 {
		for _, path := range []string{filepath.Join(o.From, parts[0]+"-agentshield", parts[1]), filepath.Join(o.From, rel)} {
			image, err := p.input(path)
			if err != nil {
				return nil, err
			}
			if image.Exists {
				return image.Data, nil
			}
		}
	}
	return embedded.ReadFile("assets/" + rel)
}
