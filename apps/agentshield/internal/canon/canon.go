// Package canon produces the canonical JSON byte form shared with the Python
// control plane: json.dumps(payload, sort_keys=True, separators=(",", ":")).
//
// Signatures (rulepack .sig, admission / grant / receipt signatures) are
// computed over these bytes on both sides, so every escaping and number
// formatting rule here must match CPython byte for byte. Differences are
// covered by canon_test.go against literal Python output.
package canon

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

// Marshal renders v in Python-compatible canonical form. v must be built from
// the JSON model: nil, bool, string, json.Number, float64, int/int64, []any,
// map[string]any.
func Marshal(v any) ([]byte, error) {
	var buf bytes.Buffer
	if err := write(&buf, v); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// Decode parses raw JSON into the generic model while preserving the original
// number literals (json.Number), so that ints stay ints and floats keep their
// shortest-repr form when re-encoded.
func Decode(raw []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if dec.More() {
		return nil, errors.New("trailing data after JSON value")
	}
	return v, nil
}

func write(buf *bytes.Buffer, v any) error {
	switch t := v.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		if t {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case string:
		writeString(buf, t)
	case json.Number:
		return writeNumber(buf, t)
	case float64:
		return writeFloat(buf, t)
	case int:
		buf.WriteString(strconv.Itoa(t))
	case int64:
		buf.WriteString(strconv.FormatInt(t, 10))
	case []any:
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := write(buf, e); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		// Python sorts str keys by code point; Go string comparison is
		// byte-wise UTF-8 which preserves code point order.
		sort.Strings(keys)
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			writeString(buf, k)
			buf.WriteByte(':')
			if err := write(buf, t[k]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("canon: unsupported type %T", v)
	}
	return nil
}

// writeString matches Python's ensure_ascii=True escaping.
func writeString(buf *bytes.Buffer, s string) {
	buf.WriteByte('"')
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		i += size
		switch {
		case r == '"':
			buf.WriteString(`\"`)
		case r == '\\':
			buf.WriteString(`\\`)
		case r == '\n':
			buf.WriteString(`\n`)
		case r == '\r':
			buf.WriteString(`\r`)
		case r == '\t':
			buf.WriteString(`\t`)
		case r == '\b':
			buf.WriteString(`\b`)
		case r == '\f':
			buf.WriteString(`\f`)
		case r < 0x20 || (r >= 0x7f && r <= 0xffff):
			// Python escapes DEL (0x7f) and everything non-ASCII.
			if r == utf8.RuneError && size == 1 {
				// invalid UTF-8 byte: Python would have failed to decode
				// earlier; emit as U+FFFD to stay deterministic.
				r = utf8.RuneError
			}
			fmt.Fprintf(buf, `\u%04x`, r)
		case r > 0xffff:
			hi, lo := utf16.EncodeRune(r)
			fmt.Fprintf(buf, `\u%04x\u%04x`, hi, lo)
		default:
			buf.WriteRune(r)
		}
	}
	buf.WriteByte('"')
}

func writeNumber(buf *bytes.Buffer, n json.Number) error {
	s := string(n)
	if !strings.ContainsAny(s, ".eE") {
		// integer literal: Python re-emits it verbatim (arbitrary precision)
		if !isIntLiteral(s) {
			return fmt.Errorf("canon: invalid integer literal %q", s)
		}
		buf.WriteString(s)
		return nil
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return fmt.Errorf("canon: invalid float literal %q", s)
	}
	return writeFloat(buf, f)
}

// writeFloat matches CPython float.__repr__ (shortest round-trip; fixed
// notation for exponents in [-4, 16), otherwise scientific with 'e' and an
// explicitly signed two-digit-minimum exponent).
func writeFloat(buf *bytes.Buffer, f float64) error {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return errors.New("canon: NaN/Inf not allowed in canonical JSON")
	}
	if f == 0 {
		if math.Signbit(f) {
			buf.WriteString("-0.0")
		} else {
			buf.WriteString("0.0")
		}
		return nil
	}
	// shortest digits via 'e' with -1 precision: d.ddddde±XX
	e := strconv.FormatFloat(f, 'e', -1, 64)
	mant, expStr, _ := strings.Cut(e, "e")
	exp, _ := strconv.Atoi(expStr)
	neg := strings.HasPrefix(mant, "-")
	mant = strings.TrimPrefix(mant, "-")
	digits := strings.Replace(mant, ".", "", 1)
	if neg {
		buf.WriteByte('-')
	}
	if exp >= -4 && exp < 16 {
		if exp >= 0 {
			intPart := digits
			frac := ""
			if len(digits) > exp+1 {
				intPart = digits[:exp+1]
				frac = digits[exp+1:]
			} else {
				intPart = digits + strings.Repeat("0", exp+1-len(digits))
			}
			if frac == "" {
				frac = "0"
			}
			buf.WriteString(intPart + "." + frac)
		} else {
			buf.WriteString("0." + strings.Repeat("0", -exp-1) + digits)
		}
		return nil
	}
	// scientific: Python repr -> "1e+16", "1.5e-05"
	m := digits[:1]
	if len(digits) > 1 {
		m += "." + digits[1:]
	}
	sign := "+"
	if exp < 0 {
		sign = "-"
		exp = -exp
	}
	fmt.Fprintf(buf, "%se%s%02d", m, sign, exp)
	return nil
}

func isIntLiteral(s string) bool {
	i := 0
	if strings.HasPrefix(s, "-") {
		i = 1
	}
	if i >= len(s) {
		return false
	}
	for ; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}
