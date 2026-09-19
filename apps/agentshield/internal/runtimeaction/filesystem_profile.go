package runtimeaction

import (
	"strings"
	"unicode/utf8"
)

// FilesystemProfile is selected by verified, versioned authority. It must not be
// inferred from a request's path spelling, client metadata, or the current OS.
type FilesystemProfile string

const (
	FilesystemPOSIXV1             FilesystemProfile = "posix/v1"
	FilesystemWindowsLocalDriveV1 FilesystemProfile = "windows-local-drive/v1"
)

func validFilesystemProfile(profile FilesystemProfile) bool {
	return profile == FilesystemPOSIXV1 || profile == FilesystemWindowsLocalDriveV1
}

// NormalizeResourceForProfile is lexical only. A Windows result does not prove
// local-volume identity, canonical on-disk case, absence of aliases/reparse
// points, or that the target cannot change before the host's operation.
func NormalizeResourceForProfile(profile FilesystemProfile, domain, value string) (string, error) {
	if !validFilesystemProfile(profile) {
		return "", ErrResource
	}
	if domain != "filesystem" || profile == FilesystemPOSIXV1 {
		return NormalizeResource(domain, value)
	}
	return normalizeWindowsLocalDrive(value)
}

func normalizeWindowsLocalDrive(value string) (string, error) {
	if !utf8.ValidString(value) || len(value) < 3 || value[1] != ':' ||
		!((value[0] >= 'A' && value[0] <= 'Z') || (value[0] >= 'a' && value[0] <= 'z')) ||
		(value[2] != '/' && value[2] != '\\') {
		return "", ErrResource
	}
	units := 0
	for _, r := range value {
		if r < 32 || r == 127 {
			return "", ErrResource
		}
		units++
		if r > 0xffff {
			units++
		}
	}
	// The first profile intentionally excludes extended/long-path semantics.
	if units > 259 {
		return "", ErrResource
	}
	canonical := strings.ToUpper(value[:1]) + strings.ReplaceAll(value[1:], `\`, "/")
	if len(canonical) == 3 {
		return canonical, nil
	}
	for _, component := range strings.Split(canonical[3:], "/") {
		if component == "" || component == "." || component == ".." ||
			strings.HasSuffix(component, ".") || strings.HasSuffix(component, " ") ||
			strings.ContainsAny(component, `<>:"|?*`) || windowsReservedComponent(component) {
			return "", ErrResource
		}
		componentUnits := 0
		for _, r := range component {
			componentUnits++
			if r > 0xffff {
				componentUnits++
			}
		}
		if componentUnits > 255 {
			return "", ErrResource
		}
	}
	return canonical, nil
}

func windowsReservedComponent(component string) bool {
	base, _, _ := strings.Cut(component, ".")
	// Windows also recognizes reserved names with spaces before an extension.
	// Reject the alias without changing ordinary component spelling.
	base = strings.ToUpper(strings.TrimRight(base, " "))
	switch base {
	case "CON", "PRN", "AUX", "NUL", "CLOCK$", "CONIN$", "CONOUT$":
		return true
	}
	for _, prefix := range []string{"COM", "LPT"} {
		if strings.HasPrefix(base, prefix) {
			suffix := strings.TrimPrefix(base, prefix)
			if len(suffix) == 1 && suffix[0] >= '1' && suffix[0] <= '9' || suffix == "¹" || suffix == "²" || suffix == "³" {
				return true
			}
		}
	}
	return false
}

// DescribeForProfile preserves the shared effect/parameter interpretation and
// changes only resource normalization. Production callers must first verify the
// signed authority that selected profile; this function creates no authority.
func DescribeForProfile(profile FilesystemProfile, tool string, params map[string]any) Descriptor {
	if !validFilesystemProfile(profile) {
		return Descriptor{Tool: tool, Operation: "invoke", Effects: []string{EffectUnknown}, ResourceError: ErrResource}
	}
	descriptor := describeWithNormalizer(tool, params, func(domain, value string) (string, error) {
		return NormalizeResourceForProfile(profile, domain, value)
	})
	if profile == FilesystemWindowsLocalDriveV1 && descriptor.ResourceError != nil {
		// Legacy POSIX descriptions retain heuristic hints on normalization
		// failure. New Windows authority must never fall back to those hints.
		descriptor.Paths = nil
	}
	return descriptor
}
