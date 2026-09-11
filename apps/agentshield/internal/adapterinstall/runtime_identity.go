package adapterinstall

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/product"
)

var managedIdentityPattern = regexp.MustCompile(`^ri-[a-f0-9]{32}$`)
var ErrIdentityWithdrawalRequired = errors.New("adapter: managed identity must be revoked before uninstall")

func validManagedTarget(o Options) bool {
	return o.Platform == Hermes && o.Instance != nil && validateInstance(o) == nil && managedIdentityPattern.MatchString(o.RuntimeIdentityID)
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
		ID         string `json:"identity_id"`
		InstanceID string `json:"instance_id"`
		AgentID    string `json:"agent_id"`
		Platform   string `json:"platform"`
	}
	if json.Unmarshal(meta.Data, &identity) != nil || identity.ID != o.RuntimeIdentityID || identity.InstanceID != o.Instance.ID || identity.AgentID != "hri-"+strings.TrimPrefix(o.Instance.ID, "hi-") || identity.Platform != Hermes {
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
	if o.Platform != Hermes {
		return "", nil
	}
	path := filepath.Join(o.configRoot(), "plugins", product.PluginDir(), "config.json")
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
	value, exists := doc["runtime_identity_id"]
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
	id, ok := doc["runtime_identity_id"].(string)
	if !ok {
		return false
	}
	if o.RuntimeIdentityID != "" && o.RuntimeIdentityID != id {
		return false
	}
	o.RuntimeIdentityID = id
	return validManagedTarget(o) && doc["token_path"] == managedCredentialPath(o) && doc["agent_id"] == "hri-"+strings.TrimPrefix(o.Instance.ID, "hi-")
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
