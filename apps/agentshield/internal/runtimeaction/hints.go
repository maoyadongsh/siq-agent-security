package runtimeaction

import (
	"encoding/json"
	"regexp"
	"sort"
	"strings"
)

var (
	urlRe     = regexp.MustCompile(`https?://([A-Za-z0-9.-]+)(?::(\d+))?`)
	hostArgRe = regexp.MustCompile(`\b(?:nc|ncat|netcat|ssh|scp|telnet)\s+(?:-\w+\s+)*([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d{1,3}(?:\.\d{1,3}){3})`)
	pathRe    = regexp.MustCompile(`(?:^|[\s"'=(,])((?:~|\$HOME|/)[A-Za-z0-9_./~-]+)`)
)

func FlattenStrings(v any) string {
	var parts []string
	var walk func(x any)
	walk = func(x any) {
		switch t := x.(type) {
		case string:
			parts = append(parts, t)
		case []any:
			for _, e := range t {
				walk(e)
			}
		case map[string]any:
			keys := make([]string, 0, len(t))
			for k := range t {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				walk(t[k])
			}
		case json.Number:
			parts = append(parts, string(t))
		}
	}
	walk(v)
	return strings.Join(parts, "\n")
}

func extractHosts(egress, fileLike bool, paramsText string) []string {
	if !egress && !fileLike {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	for _, m := range urlRe.FindAllStringSubmatch(paramsText, -1) {
		host := strings.ToLower(m[1])
		port := m[2]
		if port == "" {
			port = "80"
			if strings.HasPrefix(strings.ToLower(m[0]), "https") {
				port = "443"
			}
		}
		hp := host + ":" + port
		if !seen[hp] {
			seen[hp] = true
			out = append(out, hp)
		}
	}
	for _, m := range hostArgRe.FindAllStringSubmatch(paramsText, -1) {
		hp := strings.ToLower(m[1]) + ":0"
		if !seen[hp] {
			seen[hp] = true
			out = append(out, hp)
		}
	}
	return out
}

func extractPaths(fileLike, shellLike bool, paramsText string) []string {
	if !fileLike && !shellLike {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	for _, m := range pathRe.FindAllStringSubmatch(paramsText, -1) {
		p := strings.TrimRight(m[1], ".,;)")
		if p == "/" || seen[p] {
			continue
		}
		seen[p] = true
		out = append(out, p)
	}
	return out
}
