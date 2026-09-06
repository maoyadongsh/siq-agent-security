package main

import (
	"reflect"
	"testing"
)

func TestSplitGrantIDAndFlags(t *testing.T) {
	cases := []struct {
		name  string
		args  []string
		id    string
		flags []string
	}{
		{"doc-order", []string{"grt-1", "--approve-as", "maoyd"}, "grt-1", []string{"--approve-as", "maoyd"}},
		{"flag-first", []string{"--approve-as", "maoyd", "grt-1"}, "grt-1", []string{"--approve-as", "maoyd"}},
		{"deploy-id-only", []string{"grt-1"}, "grt-1", nil},
		{"channel", []string{"grt-1", "--channel", "console", "--approve-as", "maoyd"}, "grt-1", []string{"--channel", "console", "--approve-as", "maoyd"}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			id, flags, err := splitGrantIDAndFlags(tc.args)
			if err != nil {
				t.Fatal(err)
			}
			if id != tc.id {
				t.Fatalf("id=%q want %q", id, tc.id)
			}
			if !reflect.DeepEqual(flags, tc.flags) {
				t.Fatalf("flags=%v want %v", flags, tc.flags)
			}
		})
	}
}
