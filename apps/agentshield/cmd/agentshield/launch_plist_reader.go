package main

import (
	"encoding/xml"
	"errors"
	"io"
	"strconv"
	"strings"
)

func decodeLaunchPlist(raw string) (map[string]any, error) {
	if len(raw) == 0 || len(raw) > 65536 {
		return nil, errors.New("launch-agent: plist size invalid")
	}
	d := xml.NewDecoder(strings.NewReader(raw))
	nodes := 0
	var parse func(xml.StartElement, int) (any, error)
	next := func() (xml.Token, error) {
		for {
			token, err := d.Token()
			if err != nil {
				return nil, err
			}
			if text, ok := token.(xml.CharData); ok && strings.TrimSpace(string(text)) == "" {
				continue
			}
			return token, nil
		}
	}
	parse = func(start xml.StartElement, depth int) (any, error) {
		nodes++
		if nodes > 2048 || depth > 16 || start.Name.Space != "" || len(start.Attr) != 0 {
			return nil, errors.New("launch-agent: plist structure budget or namespace invalid")
		}
		switch start.Name.Local {
		case "string", "key", "integer":
			var text string
			for {
				token, err := d.Token()
				if err != nil {
					return nil, err
				}
				if end, ok := token.(xml.EndElement); ok && end.Name == start.Name {
					break
				}
				value, ok := token.(xml.CharData)
				if !ok {
					return nil, errors.New("launch-agent: nested scalar value")
				}
				text += string(value)
			}
			if start.Name.Local == "integer" {
				n, err := strconv.ParseInt(strings.TrimSpace(text), 10, 64)
				return n, err
			}
			return text, nil
		case "true", "false":
			token, err := next()
			if err != nil {
				return nil, err
			}
			end, ok := token.(xml.EndElement)
			if !ok || end.Name != start.Name {
				return nil, errors.New("launch-agent: malformed boolean")
			}
			return start.Name.Local == "true", nil
		case "dict":
			object := map[string]any{}
			for {
				token, err := next()
				if err != nil {
					return nil, err
				}
				if end, ok := token.(xml.EndElement); ok && end.Name == start.Name {
					return object, nil
				}
				keyStart, ok := token.(xml.StartElement)
				if !ok || keyStart.Name.Local != "key" {
					return nil, errors.New("launch-agent: dictionary key expected")
				}
				key, err := parse(keyStart, depth+1)
				if err != nil {
					return nil, err
				}
				name := key.(string)
				if _, exists := object[name]; exists {
					return nil, errors.New("launch-agent: duplicate plist key")
				}
				token, err = next()
				if err != nil {
					return nil, err
				}
				child, ok := token.(xml.StartElement)
				if !ok || child.Name.Local == "key" {
					return nil, errors.New("launch-agent: value expected")
				}
				value, err := parse(child, depth+1)
				if err != nil {
					return nil, err
				}
				object[name] = value
			}
		case "array":
			array := []any{}
			for {
				token, err := next()
				if err != nil {
					return nil, err
				}
				if end, ok := token.(xml.EndElement); ok && end.Name == start.Name {
					return array, nil
				}
				child, ok := token.(xml.StartElement)
				if !ok || child.Name.Local == "key" {
					return nil, errors.New("launch-agent: array value expected")
				}
				value, err := parse(child, depth+1)
				if err != nil {
					return nil, err
				}
				array = append(array, value)
			}
		default:
			return nil, errors.New("launch-agent: unsupported plist value")
		}
	}
	var root xml.StartElement
	for {
		token, err := next()
		if err != nil {
			return nil, err
		}
		switch v := token.(type) {
		case xml.ProcInst:
			if v.Target != "xml" {
				return nil, errors.New("launch-agent: unexpected XML instruction")
			}
		case xml.Directive:
			if !strings.HasPrefix(string(v), "DOCTYPE plist PUBLIC ") || strings.Contains(string(v), "[") {
				return nil, errors.New("launch-agent: unexpected XML declaration")
			}
		case xml.StartElement:
			root = v
		default:
			return nil, errors.New("launch-agent: plist root expected")
		}
		if root.Name.Local != "" {
			break
		}
	}
	if root.Name.Local != "plist" || root.Name.Space != "" || len(root.Attr) != 1 || root.Attr[0].Name.Space != "" || root.Attr[0].Name.Local != "version" || root.Attr[0].Value != "1.0" {
		return nil, errors.New("launch-agent: invalid plist root")
	}
	token, err := next()
	if err != nil {
		return nil, err
	}
	dict, ok := token.(xml.StartElement)
	if !ok || dict.Name.Local != "dict" {
		return nil, errors.New("launch-agent: root dictionary required")
	}
	value, err := parse(dict, 0)
	if err != nil {
		return nil, err
	}
	token, err = next()
	if err != nil {
		return nil, err
	}
	end, ok := token.(xml.EndElement)
	if !ok || end.Name != root.Name {
		return nil, errors.New("launch-agent: invalid plist ending")
	}
	if _, err = next(); err != io.EOF {
		return nil, errors.New("launch-agent: trailing plist content")
	}
	return value.(map[string]any), nil
}
