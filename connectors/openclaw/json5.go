package main

import (
	"encoding/json"
	"regexp"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

var configDecimal = regexp.MustCompile(`^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?$|^[+-]?\.[0-9]+(?:[eE][+-]?[0-9]+)?$`)

func configSpace(r rune) bool {
	return unicode.Is(unicode.Zs, r) || strings.ContainsRune(" \t\v\f\r\n\u2028\u2029\ufeff", r)
}

// Normalize data syntax only; there is no evaluator, environment expansion or
// include loader. Keep duplicate keys intact for the subsequent strict walker.
func normalizeConfigJSON5(data []byte) ([]byte, error) {
	if len(data) > 16<<20 || !utf8.Valid(data) {
		return nil, errConfigInvalid
	}
	s := string(data)
	tokens := make([]string, 0)
	for i := 0; i < len(s); {
		if len(tokens) >= 262144 {
			return nil, errConfigInvalid
		}
		r, size := utf8.DecodeRuneInString(s[i:])
		if configSpace(r) {
			i += size
			continue
		}
		if strings.HasPrefix(s[i:], "//") {
			i += 2
			for i < len(s) {
				r, size = utf8.DecodeRuneInString(s[i:])
				if strings.ContainsRune("\r\n\u2028\u2029", r) {
					break
				}
				i += size
			}
			continue
		}
		if strings.HasPrefix(s[i:], "/*") {
			end := strings.Index(s[i+2:], "*/")
			if end < 0 {
				return nil, errConfigInvalid
			}
			i += end + 4
			continue
		}
		if strings.ContainsRune("{}[]:,", r) {
			tokens = append(tokens, string(r))
			i += size
			continue
		}
		if r == '\'' || r == '"' {
			value, next, err := configString(s, i)
			if err != nil {
				return nil, err
			}
			encoded, _ := json.Marshal(value)
			tokens = append(tokens, string(encoded))
			i = next
			continue
		}
		start := i
		for i < len(s) {
			r, size = utf8.DecodeRuneInString(s[i:])
			if configSpace(r) || strings.ContainsRune("{}[]:,/", r) {
				break
			}
			i += size
		}
		if i == start {
			return nil, errConfigInvalid
		}
		word := s[start:i]
		// Object identifiers occur only immediately after an opening object or comma;
		// final JSON validation still checks the colon and surrounding structure.
		isKey := len(tokens) > 0 && (tokens[len(tokens)-1] == "{" || tokens[len(tokens)-1] == ",")
		identifier := word
		if strings.Contains(word, `\`) {
			for j := 0; j < len(word); j++ {
				if word[j] == '\\' {
					if j+5 >= len(word) || word[j+1] != 'u' {
						return nil, errConfigInvalid
					}
					j += 5
				}
			}
			if json.Unmarshal([]byte(`"`+word+`"`), &identifier) != nil {
				return nil, errConfigInvalid
			}
		}
		if isKey && configIdentifier(identifier) {
			// Lookahead must be a colon, allowing comments without interpreting them.
			j := i
			for j < len(s) {
				v, n := utf8.DecodeRuneInString(s[j:])
				if configSpace(v) {
					j += n
					continue
				}
				if strings.HasPrefix(s[j:], "/*") {
					end := strings.Index(s[j+2:], "*/")
					if end < 0 {
						return nil, errConfigInvalid
					}
					j += end + 4
					continue
				}
				if strings.HasPrefix(s[j:], "//") {
					j += 2
					for j < len(s) {
						v, n = utf8.DecodeRuneInString(s[j:])
						if strings.ContainsRune("\r\n\u2028\u2029", v) {
							break
						}
						j += n
					}
					continue
				}
				break
			}
			if j < len(s) && s[j] == ':' {
				encoded, _ := json.Marshal(identifier)
				tokens = append(tokens, string(encoded))
				continue
			}
		}
		if word == "true" || word == "false" || word == "null" {
			tokens = append(tokens, word)
			continue
		}
		number, err := configNumber(word)
		if err != nil {
			return nil, err
		}
		tokens = append(tokens, number)
	}
	var out strings.Builder
	for i, token := range tokens {
		if token == "," && i > 0 && !strings.Contains("{[,:", tokens[i-1]) && i+1 < len(tokens) && (tokens[i+1] == "}" || tokens[i+1] == "]") {
			continue
		}
		out.WriteString(token)
		out.WriteByte(' ')
		if out.Len() > 32<<20 {
			return nil, errConfigInvalid
		}
	}
	return []byte(out.String()), nil
}

func configIdentifier(s string) bool {
	for i, r := range s {
		if r == '$' || r == '_' || unicode.IsLetter(r) || unicode.In(r, unicode.Nl) {
			continue
		}
		if i > 0 && (unicode.IsDigit(r) || unicode.In(r, unicode.Mn, unicode.Mc, unicode.Pc) || r == '\u200c' || r == '\u200d') {
			continue
		}
		return false
	}
	return s != ""
}

func configNumber(s string) (string, error) {
	sign, n := "", s
	if len(n) > 0 && (n[0] == '+' || n[0] == '-') {
		if n[0] == '-' {
			sign = "-"
		}
		n = n[1:]
	}
	if strings.HasPrefix(n, "0x") || strings.HasPrefix(n, "0X") {
		value, err := strconv.ParseUint(n[2:], 16, 64)
		if err != nil {
			return "", errConfigInvalid
		}
		return sign + strconv.FormatUint(value, 10), nil
	}
	if !configDecimal.MatchString(s) {
		return "", errConfigInvalid
	}
	n = strings.TrimPrefix(s, "+")
	if strings.HasPrefix(n, ".") {
		n = "0" + n
	}
	if strings.HasPrefix(n, "-.") {
		n = "-0" + n[1:]
	}
	parts := strings.FieldsFunc(n, func(r rune) bool { return r == 'e' || r == 'E' })
	if len(parts) > 0 && strings.HasSuffix(parts[0], ".") {
		n = strings.Replace(n, ".", ".0", 1)
	}
	return n, nil
}

func configString(s string, start int) (string, int, error) {
	quote := s[start]
	var literal strings.Builder
	literal.WriteByte('"')
	for i := start + 1; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		i += size
		if r == rune(quote) {
			literal.WriteByte('"')
			var value string
			if json.Unmarshal([]byte(literal.String()), &value) != nil {
				return "", 0, errConfigInvalid
			}
			return value, i, nil
		}
		if r == '\n' || r == '\r' || r == '\u2028' || r == '\u2029' || r < 0x20 {
			return "", 0, errConfigInvalid
		}
		if r != '\\' {
			if r == '"' {
				literal.WriteByte('\\')
			}
			literal.WriteRune(r)
			continue
		}
		if i >= len(s) {
			return "", 0, errConfigInvalid
		}
		r, size = utf8.DecodeRuneInString(s[i:])
		i += size
		switch r {
		case '\n', '\u2028', '\u2029':
			continue
		case '\r':
			if i < len(s) && s[i] == '\n' {
				i++
			}
			continue
		case 'u', 'x':
			n := 4
			if r == 'x' {
				n = 2
			}
			if i+n > len(s) {
				return "", 0, errConfigInvalid
			}
			if _, err := strconv.ParseUint(s[i:i+n], 16, 16); err != nil {
				return "", 0, errConfigInvalid
			}
			literal.WriteString(`\u`)
			if n == 2 {
				literal.WriteString("00")
			}
			literal.WriteString(s[i : i+n])
			i += n
		case '0':
			if i < len(s) && s[i] >= '0' && s[i] <= '9' {
				return "", 0, errConfigInvalid
			}
			literal.WriteString(`\u0000`)
		case 'v':
			literal.WriteString(`\u000b`)
		case 'b', 'f', 'n', 'r', 't', '\\', '"', '/':
			literal.WriteByte('\\')
			literal.WriteRune(r)
		default:
			if r >= '1' && r <= '9' {
				return "", 0, errConfigInvalid
			}
			literal.WriteRune(r)
		}
	}
	return "", 0, errConfigInvalid
}
