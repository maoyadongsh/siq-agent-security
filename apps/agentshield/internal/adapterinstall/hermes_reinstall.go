package adapterinstall

import (
	"bytes"
	"encoding/json"
	"fmt"
	"path/filepath"

	"siq-agent-security/apps/agentshield/internal/state"
)

// Native uninstall preserves unrelated current fields and normalizes YAML.
// Reuse only the original snapshot pinned by that authenticated uninstall;
// never equate an arbitrary YAML file or backup with installation ownership.
func (p *Plan) hermesReinstallSnapshot(path, original string, snapshot fileImage) bool {
	o := p.payload.Options
	if o.Platform != Hermes || !o.NativeEnable || o.Instance == nil || path != filepath.Join(o.configRoot(), "config.yaml") || original != path+originalSuffix {
		return false
	}
	st := &state.Store{Dir: o.StateDir}
	rev, raw, err := st.LatestSeq("adapter-operations", operationKey(o))
	if err != nil || rev < 0 {
		return false
	}
	var claim operationClaim
	if json.Unmarshal(raw, &claim) != nil || claim.Schema != "adapter-operation/v1" || claim.Platform != Hermes || claim.Action != "uninstall" {
		return false
	}
	status, err := endState(o.StateDir, claim)
	if err != nil || status != "committed" {
		return false
	}
	prior, err := unsealPlan(o.StateDir, claim)
	if err != nil || prior.payload.Options.Platform != Hermes || prior.payload.Options.Instance == nil ||
		prior.payload.Options.Instance.ID != o.Instance.ID || prior.payload.Options.configRoot() != o.configRoot() ||
		prior.payload.Record.InstanceID != o.Instance.ID || prior.payload.Record.ConfigDir != o.configRoot() ||
		prior.payload.Record.NativeOriginal == nil || prior.payload.Record.Modified[path] != original {
		return false
	}
	pinned, ok := prior.payload.Inputs[original]
	if ok && pinned.Exists {
		return snapshot.Exists && bytes.Equal(pinned.Data, snapshot.Data)
	}
	// Older native uninstall plans restore only the product's registration and
	// need not read the raw backup. Find its authenticated installation image in
	// bounded history; absence, corruption or exceeding the bound fails closed.
	for index, scanned := rev-1, 0; index >= 0 && scanned < 64; index, scanned = index-1, scanned+1 {
		raw, err := privateRead(filepath.Join(o.StateDir, "adapter-operations", fmt.Sprintf("%s.%d.json", operationKey(o), index)), 2<<20)
		if err != nil || json.Unmarshal(raw, &claim) != nil || claim.Schema != "adapter-operation/v1" || claim.Platform != Hermes {
			return false
		}
		status, err := endState(o.StateDir, claim)
		if err != nil || status == "" {
			return false
		}
		if status != "committed" || claim.Action != "install" {
			continue
		}
		installed, err := unsealPlan(o.StateDir, claim)
		if err != nil || installed.payload.Options.Platform != Hermes || installed.payload.Options.Instance == nil ||
			installed.payload.Options.Instance.ID != o.Instance.ID || installed.payload.Options.configRoot() != o.configRoot() ||
			installed.payload.Record.Modified[path] != original || installed.payload.Record.NativeOriginal == nil {
			return false
		}
		if pinned, ok := installed.payload.Inputs[original]; ok && pinned.Exists {
			return snapshot.Exists && bytes.Equal(pinned.Data, snapshot.Data)
		}
		for _, change := range installed.payload.Files {
			if change.Path == original {
				return change.After.Exists && snapshot.Exists && bytes.Equal(change.After.Data, snapshot.Data)
			}
		}
	}
	return false
}
