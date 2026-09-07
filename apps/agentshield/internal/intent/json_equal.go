package intent

import (
	"bytes"
	"encoding/json"
	"math/big"
)

// jsonEqual compares JSON values without rounding integers through float64 or
// expanding huge exponents. Native callers first pass through their JSON form.
func jsonEqual(a, b any) bool {
	decode := func(v any) (any, error) {
		raw, err := json.Marshal(v)
		if err != nil {
			return nil, err
		}
		var out any
		d := json.NewDecoder(bytes.NewReader(raw))
		d.UseNumber()
		err = d.Decode(&out)
		return out, err
	}
	aa, e1 := decode(a)
	bb, e2 := decode(b)
	return e1 == nil && e2 == nil && equalJSONValue(aa, bb)
}
func equalJSONValue(a, b any) bool {
	switch x := a.(type) {
	case nil:
		return b == nil
	case bool:
		y, ok := b.(bool)
		return ok && x == y
	case string:
		y, ok := b.(string)
		return ok && x == y
	case json.Number:
		y, ok := b.(json.Number)
		if !ok {
			return false
		}
		xc, xe, xok := decimalParts(string(x))
		yc, ye, yok := decimalParts(string(y))
		return xok && yok && xc == yc && xe == ye
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !equalJSONValue(x[i], y[i]) {
				return false
			}
		}
		return true
	case map[string]any:
		y, ok := b.(map[string]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for k, v := range x {
			w, exists := y[k]
			if !exists || !equalJSONValue(v, w) {
				return false
			}
		}
		return true
	default:
		return false
	}
}

// The decoder already checked JSON number syntax. Coefficient + decimal exponent
// preserve exact equality (1 == 1.0) with work bounded by the input length.
func decimalParts(s string) (string, string, bool) {
	if len(s) > 1024 {
		return "", "", false
	}
	sign := ""
	if s[0] == '-' {
		sign = "-"
		s = s[1:]
	}
	exponent := new(big.Int)
	for i, c := range s {
		if c == 'e' || c == 'E' {
			if _, ok := exponent.SetString(s[i+1:], 10); !ok {
				return "", "", false
			}
			s = s[:i]
			break
		}
	}
	coefficient := make([]byte, 0, len(s))
	fraction := 0
	dot := false
	for i := range s {
		if s[i] == '.' {
			dot = true
			continue
		}
		coefficient = append(coefficient, s[i])
		if dot {
			fraction++
		}
	}
	for len(coefficient) > 0 && coefficient[0] == '0' {
		coefficient = coefficient[1:]
	}
	if len(coefficient) == 0 {
		return "0", "0", true
	}
	trailing := 0
	for coefficient[len(coefficient)-1] == '0' {
		coefficient = coefficient[:len(coefficient)-1]
		trailing++
	}
	exponent.Add(exponent, big.NewInt(int64(trailing-fraction)))
	return sign + string(coefficient), exponent.String(), true
}
