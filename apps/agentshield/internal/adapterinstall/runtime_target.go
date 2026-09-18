package adapterinstall

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"path/filepath"
	"runtime"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/runtimepath"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

// RuntimeTarget is internal launch metadata, never a raw HTTP input or response.
type RuntimeTarget struct {
	InstanceID         string
	ProfilePath        string
	Home               string
	NativeCLI          string
	Digest             string
	FilesystemProfile  runtimeaction.FilesystemProfile
	RootIdentityDigest string
}

// InspectRuntimeTarget pins the files checked by configuration diagnostics. It
// does not execute the host or attest the whole Python dependency environment.
func InspectRuntimeTarget(opts Options) (RuntimeTarget, error) {
	var out RuntimeTarget
	if err := opts.normalise(); err != nil {
		return out, errors.New("runtime_check_configuration_not_ready")
	}
	if opts.Platform != Hermes || opts.Instance == nil || validateInstance(opts) != nil {
		return out, errors.New("runtime_check_instance_unsupported")
	}
	if Inspect(opts).ConfigurationState != "ready" {
		return out, errors.New("runtime_check_configuration_not_ready")
	}
	record, err := newestInstanceRecord(opts)
	if err != nil {
		return out, errors.New("runtime_check_configuration_not_ready")
	}
	cli := FindHermesCLI(opts.NativeCLI)
	if cli == "" || cli != record.NativeCLI {
		return out, errors.New("runtime_check_native_changed")
	}
	nativeHash, err := programDigest(cli)
	if err != nil || nativeHash != record.NativeCLIHash {
		return out, errors.New("runtime_check_native_changed")
	}
	serviceHash, err := programDigest(opts.Binary)
	if err != nil {
		return out, errors.New("runtime_check_service_unavailable")
	}
	var profile runtimeaction.FilesystemProfile
	var rootIdentity string
	if runtime.GOOS == "windows" {
		// Explicit state activation and a trusted installed target jointly select
		// this profile; no request path, cwd or drive can choose it.
		if stateformat.RequireWindowsProfile(opts.StateDir) != nil {
			return out, errors.New("runtime_check_windows_profile_required")
		}
		facts, e := runtimepath.InspectWindows(opts.configRoot(), false)
		if e != nil || !facts.IsDirectory() {
			return out, errors.New("runtime_check_configuration_unavailable")
		}
		rootIdentity, e = facts.IdentityDigest()
		if e != nil {
			return out, errors.New("runtime_check_configuration_unavailable")
		}
		profile = runtimeaction.FilesystemWindowsLocalDriveV1
	}
	material := map[string]any{"instance_id": opts.Instance.ID, "profile": opts.configRoot(), "native_cli": cli, "native_sha256": nativeHash, "service_sha256": serviceHash, "mode": opts.Mode, "endpoint": opts.Endpoint}
	if profile != "" {
		material["filesystem_profile"], material["root_identity_digest"] = string(profile), rootIdentity
	}
	for _, name := range []string{"config.yaml", filepath.Join("plugins", product.PluginDir(), "plugin.yaml"), filepath.Join("plugins", product.PluginDir(), "__init__.py"), filepath.Join("plugins", product.PluginDir(), "config.json")} {
		raw, err := inspectRead(opts.Home, filepath.Join(opts.configRoot(), name))
		if err != nil {
			return out, errors.New("runtime_check_configuration_unavailable")
		}
		hash := sha256.Sum256(raw)
		material[filepath.ToSlash(name)] = hex.EncodeToString(hash[:])
	}
	raw, err := canon.Marshal(material)
	if err != nil {
		return out, errors.New("runtime_check_snapshot_failed")
	}
	hash := sha256.Sum256(raw)
	return RuntimeTarget{InstanceID: opts.Instance.ID, ProfilePath: opts.configRoot(), Home: opts.Home, NativeCLI: cli, Digest: hex.EncodeToString(hash[:]), FilesystemProfile: profile, RootIdentityDigest: rootIdentity}, nil
}
