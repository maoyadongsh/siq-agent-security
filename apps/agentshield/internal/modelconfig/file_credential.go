package modelconfig

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func fileCredential(ref, providers map[string]any) (string, string) {
	if len(ref) != 3 || str(ref, "source") != "file" {
		return "", "unsupported"
	}
	provider := mapAt(providers, str(ref, "provider"))
	path, mode := str(provider, "path"), str(provider, "mode")
	if str(provider, "source") != "file" || !filepath.IsAbs(path) || mode != "json" || strings.Contains(path, "${") {
		return "", "unsupported"
	}
	raw, err := readBoundedFile(filepath.Dir(path), filepath.Base(path), true)
	if os.IsNotExist(err) {
		return "", "missing"
	}
	if err != nil || !uniqueJSON(raw) {
		return "", "unsupported"
	}
	if limit, exists := provider["maxBytes"]; exists {
		n, ok := limit.(float64)
		if !ok || n <= 0 || n != float64(int64(n)) || float64(len(raw)) > n {
			return "", "unsupported"
		}
	}
	pointer := str(ref, "id")
	if !strings.HasPrefix(pointer, "/") || len(pointer) > 1024 {
		return "", "unsupported"
	}
	var value any
	if json.Unmarshal(raw, &value) != nil {
		return "", "unsupported"
	}
	for _, part := range strings.Split(pointer[1:], "/") {
		// JSON Pointer escapes are decoded once. Unknown escapes are invalid.
		for i := 0; i < len(part); i++ {
			if part[i] == '~' {
				if i+1 >= len(part) || (part[i+1] != '0' && part[i+1] != '1') {
					return "", "unsupported"
				}
				i++
			}
		}
		key := strings.ReplaceAll(strings.ReplaceAll(part, "~1", "/"), "~0", "~")
		switch v := value.(type) {
		case map[string]any:
			value = v[key]
		case []any:
			i, e := strconv.Atoi(key)
			if e != nil || strconv.Itoa(i) != key || i < 0 || i >= len(v) {
				return "", "unsupported"
			}
			value = v[i]
		default:
			return "", "unsupported"
		}
	}
	key, ok := value.(string)
	if !ok || strings.ContainsAny(key, "\r\n") {
		return "", "unsupported"
	}
	if key == "" {
		return "", "missing"
	}
	return key, "present"
}
