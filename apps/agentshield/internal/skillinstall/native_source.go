package skillinstall

import (
	"bytes"
	"context"
	"path"
	"path/filepath"
	"runtime"
	"strings"
	"unicode"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/skillimport"
)

type NativeSourceFile struct {
	PathSHA256 string `json:"path_sha256"`
	SHA256     string `json:"sha256"`
	Bytes      int64  `json:"bytes"`
}

// NativeSourceSnapshot contains no document body. HostRoot is internal-only:
// the trusted launch verifier must prove the corresponding read-only mount.
type NativeSourceSnapshot struct {
	InstallID      string
	ClaimSignature string
	InstanceID     string
	HostRoot       string `json:"-"`
	Main           NativeSourceFile
	Content        NativeSourceFile
	TextSHA256     string
}

func ValidNativeRoot(root string) bool {
	return len(root) <= 4096 && root != "/" && path.IsAbs(root) && path.Clean(root) == root && utf8.ValidString(root) && !strings.Contains(root, "\\") && strings.IndexFunc(root, unicode.IsControl) < 0
}

// ReadNativeSource selects only signed manifest paths, never a caller path.
// It is for the Linux native profile and does not assert that a mount exists.
func (s *Store) ReadNativeSource(ctx context.Context, id, instance, runtimeRoot, contentPathSHA string) (*NativeSourceSnapshot, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if runtime.GOOS != "linux" || !ValidNativeRoot(runtimeRoot) || !digestPattern.MatchString(contentPathSHA) {
		return nil, ErrInvalid
	}
	c, err := s.claim(ctx, id)
	if err != nil || c.Plan.Platform != "hermes" || c.Plan.InstanceID != instance {
		return nil, ErrChanged
	}
	g, _, err := s.authority.GetGrantWithSeq(c.Plan.GrantID)
	if err != nil || s.ValidateRuntimeGrant(ctx, g) != nil {
		return nil, ErrChanged
	}
	binding, err := s.runtimeBinding(ctx, g.GrantID)
	if err != nil || binding.InstallID != id {
		return nil, ErrChanged
	}
	root, _, err := s.destination(ctx, c.Plan)
	if err != nil {
		return nil, ErrChanged
	}
	var main, content *skillimport.File
	for i := range c.Files {
		file := &c.Files[i]
		if file.Path == "SKILL.md" {
			main = file
		}
		if hash([]byte(path.Join(runtimeRoot, file.Path))) == contentPathSHA {
			if content != nil {
				return nil, ErrChanged
			}
			content = file
		}
	}
	if main == nil || content == nil {
		return nil, ErrChanged
	}
	read := func(file *skillimport.File) ([]byte, NativeSourceFile, error) {
		if file.Bytes > 1<<20 {
			return nil, NativeSourceFile{}, ErrLimit
		}
		raw, _, err := readBounded(ctx, filepath.Join(root, filepath.FromSlash(file.Path)), 1<<20)
		if err != nil || int64(len(raw)) != file.Bytes || hash(raw) != file.SHA256 {
			return nil, NativeSourceFile{}, ErrChanged
		}
		return raw, NativeSourceFile{PathSHA256: hash([]byte(path.Join(runtimeRoot, file.Path))), SHA256: file.SHA256, Bytes: file.Bytes}, nil
	}
	raw, mainMeta, err := read(main)
	if err != nil {
		return nil, err
	}
	contentMeta := mainMeta
	if content.Path != main.Path {
		raw, contentMeta, err = read(content)
		if err != nil {
			return nil, err
		}
	}
	out := &NativeSourceSnapshot{InstallID: id, ClaimSignature: c.Signature, InstanceID: instance, HostRoot: root, Main: mainMeta, Content: contentMeta, TextSHA256: hash(nativeDecodedText(raw))}
	// Recheck the entire approved import/target and current runtime binding;
	// matching just one observed file cannot prove an installation is unchanged.
	if s.ValidateRuntimeGrant(ctx, g) != nil {
		return nil, ErrChanged
	}
	current, _, err := s.destination(ctx, c.Plan)
	if err != nil || current != root || ctx.Err() != nil {
		return nil, ErrChanged
	}
	return out, nil
}

// Match CPython UTF-8 errors=replace, which consumes a valid partial prefix as
// one error but does not collapse consecutive invalid start bytes. Go's
// strings.ToValidUTF8 coalesces runs and is not equivalent.
func nativeDecodedText(raw []byte) []byte {
	raw = bytes.TrimPrefix(raw, []byte{0xef, 0xbb, 0xbf})
	out := make([]byte, 0, len(raw))
	for len(raw) > 0 {
		r, n := utf8.DecodeRune(raw)
		if r == utf8.RuneError && n == 1 {
			size := 0
			switch {
			case raw[0] >= 0xc2 && raw[0] <= 0xdf:
				size = 2
			case raw[0] >= 0xe0 && raw[0] <= 0xef:
				size = 3
			case raw[0] >= 0xf0 && raw[0] <= 0xf4:
				size = 4
			}
			n = 1
			for n < size && n < len(raw) {
				b := raw[n]
				if b < 0x80 || b > 0xbf {
					break
				}
				if n == 1 && ((raw[0] == 0xe0 && b < 0xa0) || (raw[0] == 0xed && b >= 0xa0) || (raw[0] == 0xf0 && b < 0x90) || (raw[0] == 0xf4 && b >= 0x90)) {
					break
				}
				n++
			}
			out = utf8.AppendRune(out, utf8.RuneError)
		} else {
			out = append(out, raw[:n]...)
		}
		raw = raw[n:]
	}
	out = bytes.ReplaceAll(out, []byte("\r\n"), []byte("\n"))
	return bytes.ReplaceAll(out, []byte("\r"), []byte("\n"))
}
