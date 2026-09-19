package adapterinstall

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/product"
)

var managedIdentityPattern = regexp.MustCompile(`^ri-[a-f0-9]{32}$`)
var ErrIdentityWithdrawalRequired = errors.New("adapter: managed identity must be revoked before uninstall")

// Managed config field names differ by host convention: Hermes plugin
// config.json uses snake_case, OpenClaw's product config uses camelCase.
func managedConfigKeys(platform string) (id, token, agent string) {
	if platform == WorkBuddy {
		return "runtime_identity_id", "credential_path", "agent_id"
	}
	if platform == OpenClaw {
		return "runtimeIdentityId", "tokenPath", "agentId"
	}
	return "runtime_identity_id", "token_path", "agent_id"
}

func validManagedTarget(o Options) bool {
	return (o.Platform == Hermes || o.Platform == OpenClaw || o.Platform == WorkBuddy && runtime.GOOS == "windows") && o.Instance != nil && validateInstance(o) == nil && managedIdentityPattern.MatchString(o.RuntimeIdentityID)
}
func managedCredentialPath(o Options) string {
	return filepath.Join(o.StateDir, "runtime-identity-secrets", o.RuntimeIdentityID+".token")
}
func managedRevocationPath(o Options) string {
	return filepath.Join(o.StateDir, "runtime-identity-revocations", o.RuntimeIdentityID+".json")
}

// Pin public signed metadata and the absence of revocation, never secret bytes.
// The server separately verifies signatures and current Grant authority.
func (p *Plan) pinRuntimeIdentity() error {
	o := p.payload.Options
	if !validManagedTarget(o) {
		return ErrPlanChanged
	}
	meta, err := p.input(filepath.Join(o.StateDir, "runtime-identities", o.RuntimeIdentityID+".json"))
	if err != nil || !meta.Exists || len(meta.Data) > 16<<10 {
		return ErrPlanChanged
	}
	var identity struct {
		SchemaVersion     string `json:"schema_version"`
		FilesystemProfile string `json:"filesystem_profile"`
		ID                string `json:"identity_id"`
		InstanceID        string `json:"instance_id"`
		AgentID           string `json:"agent_id"`
		Platform          string `json:"platform"`
	}
	if json.Unmarshal(meta.Data, &identity) != nil || identity.ID != o.RuntimeIdentityID || identity.InstanceID != o.Instance.ID || identity.AgentID != "hri-"+strings.TrimPrefix(o.Instance.ID, "hi-") || identity.Platform != o.Platform {
		return ErrPlanChanged
	}
	if o.Platform == WorkBuddy && (identity.SchemaVersion != "local-runtime-identity/v2" || identity.FilesystemProfile != "windows-local-drive/v1") {
		return ErrPlanChanged
	}
	revoked, err := p.input(managedRevocationPath(o))
	if err != nil || revoked.Exists {
		return ErrPlanChanged
	}
	return nil
}

// ConfiguredRuntimeIdentity reads only the adapter's non-secret config reference.
func ConfiguredRuntimeIdentity(o Options) (string, error) {
	idKey := "runtime_identity_id"
	path := filepath.Join(o.configRoot(), "plugins", product.PluginDir(), "config.json")
	if o.Platform == OpenClaw {
		idKey = "runtimeIdentityId"
		path = filepath.Join(o.configRoot(), product.Name+".json")
	} else if o.Platform == WorkBuddy {
		path = workBuddyManagedConfigPath(o)
	} else if o.Platform != Hermes {
		return "", nil
	}
	if _, err := os.Lstat(path); errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	doc, err := inspectJSON(o.Home, path)
	if errors.Is(err, os.ErrNotExist) {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	if o.Platform == WorkBuddy {
		raw, err := inspectRead(o.Home, path)
		if err != nil {
			return "", err
		}
		cfg, err := adapters.DecodeWorkBuddyManagedConfig(raw, path, o.StateDir)
		if err != nil {
			return "", ErrPlanChanged
		}
		return cfg.RuntimeIdentityID, nil
	}
	value, exists := doc[idKey]
	if !exists {
		return "", nil
	}
	id, ok := value.(string)
	if !ok || !managedIdentityPattern.MatchString(id) {
		return "", ErrPlanChanged
	}
	return id, nil
}

func managedConnectionMatches(o Options, doc map[string]any) bool {
	if o.Instance == nil {
		root := o.configRoot()
		o.Instance = &InstanceTarget{ID: hermeshome.Identifier(root), Name: "default", ConfigDir: root}
	}
	idKey, tokenKey, agentKey := managedConfigKeys(o.Platform)
	id, ok := doc[idKey].(string)
	if !ok {
		return false
	}
	if o.RuntimeIdentityID != "" && o.RuntimeIdentityID != id {
		return false
	}
	o.RuntimeIdentityID = id
	return validManagedTarget(o) && doc[tokenKey] == managedCredentialPath(o) && doc[agentKey] == "hri-"+strings.TrimPrefix(o.Instance.ID, "hi-")
}

// Direct CLI/package callers cannot remove managed hooks while the credential
// remains active. The admin API publishes the signed revocation first. Any
// malformed tombstone also makes runtimeidentity authentication fail closed.
func (p *Plan) requireIdentityWithdrawal() error {
	o := p.payload.Options
	if p.payload.View.Action != "uninstall" || o.RuntimeIdentityID == "" {
		return nil
	}
	if !validManagedTarget(o) {
		return ErrPlanChanged
	}
	image, err := readImage(o.Home, managedRevocationPath(o))
	if err != nil || !image.Exists {
		return ErrIdentityWithdrawalRequired
	}
	return nil
}
