package intent

import (
	"bytes"
	"encoding/json"
	"io"
	"reflect"
	"strings"
)

// New versioned authority has exact names and no duplicate fields throughout
// its typed structure. Interface values are user data, not authority fields.
// Legacy decoding is unchanged except that new fields cannot be smuggled in.
func exactProfileFields(raw []byte, shape any) bool {
	return exactProfileValue(raw, reflect.TypeOf(shape))
}

func exactProfileValue(raw []byte, t reflect.Type) bool {
	for t.Kind() == reflect.Pointer {
		t = t.Elem()
	}
	if t.Kind() == reflect.Slice || t.Kind() == reflect.Array {
		var values []json.RawMessage
		if json.Unmarshal(raw, &values) != nil {
			return false
		}
		for _, value := range values {
			if !exactProfileValue(value, t.Elem()) {
				return false
			}
		}
		return true
	}
	if t.Kind() != reflect.Struct {
		// The normal decoder validates scalar types. In particular, do not
		// interpret arbitrary parameter value/values objects as Go structures.
		return true
	}
	allowed := map[string]reflect.Type{}
	for i := 0; i < t.NumField(); i++ {
		field := t.Field(i)
		name := strings.Split(field.Tag.Get("json"), ",")[0]
		if name != "" && name != "-" {
			allowed[name] = field.Type
		}
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	start, err := d.Token()
	if err != nil || start != json.Delim('{') {
		return false
	}
	seen := map[string]bool{}
	for d.More() {
		key, err := d.Token()
		name, ok := key.(string)
		fieldType, exists := allowed[name]
		if err != nil || !ok || !exists || seen[name] {
			return false
		}
		seen[name] = true
		var value json.RawMessage
		if d.Decode(&value) != nil || !exactProfileValue(value, fieldType) {
			return false
		}
	}
	if end, err := d.Token(); err != nil || end != json.Delim('}') {
		return false
	}
	var extra any
	return d.Decode(&extra) == io.EOF
}

func (r *GrantReference) UnmarshalJSON(raw []byte) error {
	type wire GrantReference
	var value wire
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&value) != nil {
		return violation("intent_invalid_grant_selection")
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return violation("intent_invalid_grant_selection")
	}
	for field := range fields {
		if strings.EqualFold(field, "permission_digest_schema") && (field != "permission_digest_schema" || value.PermissionDigestSchema != "grant-permissions/v2") {
			return violation("intent_invalid_grant_selection")
		}
	}
	if value.PermissionDigestSchema != "" && !exactProfileFields(raw, value) {
		return violation("intent_invalid_grant_selection")
	}
	*r = GrantReference(value)
	return nil
}

func (b *Binding) UnmarshalJSON(raw []byte) error {
	type wire Binding
	var value wire
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&value) != nil {
		return violation("intent_invalid_binding")
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil {
		return violation("intent_invalid_binding")
	}
	for field := range fields {
		if strings.EqualFold(field, "schema_version") && (field != "schema_version" || value.SchemaVersion != "intent-grant-binding/v2") {
			return violation("intent_invalid_binding")
		}
	}
	if value.SchemaVersion != "" {
		if value.SchemaVersion != "intent-grant-binding/v2" || value.GrantRef == nil || value.GrantRef.PermissionDigestSchema != "grant-permissions/v2" || !exactProfileFields(raw, value) {
			return violation("intent_invalid_binding")
		}
	} else if value.GrantRef != nil && value.GrantRef.PermissionDigestSchema != "" {
		return violation("intent_invalid_binding")
	}
	*b = Binding(value)
	return nil
}
