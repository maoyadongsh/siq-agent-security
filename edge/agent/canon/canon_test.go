package canon

import (
	"encoding/json"
	"testing"
)

// Expected strings are literal CPython output of
// json.dumps(obj, sort_keys=True, separators=(",", ":")).
func TestMarshalMatchesPython(t *testing.T) {
	cases := []struct {
		name string
		in   string // JSON input (any key order / formatting)
		want string
	}{
		{
			"escapes and unicode",
			`{"b":1,"a":[1,2.5,true,null,"x"],"c":{"z":"中文","y":"emoji 😀","w":"tab\tnl\n\"q\" \\ \u007f \u0001"}}`,
			`{"a":[1,2.5,true,null,"x"],"b":1,"c":{"w":"tab\tnl\n\"q\" \\ \u007f \u0001","y":"emoji \ud83d\ude00","z":"\u4e2d\u6587"}}`,
		},
		{
			"float repr",
			`{"f":[0.85,0.95,1.0,100.0,1e16,1e15,0.0001,0.00001,1.5e-7,-0.0,123456789.125,2.5e-5,1e22]}`,
			`{"f":[0.85,0.95,1.0,100.0,1e+16,1000000000000000.0,0.0001,1e-05,1.5e-07,-0.0,123456789.125,2.5e-05,1e+22]}`,
		},
		{
			"integers incl. beyond int64",
			`{"n":[0,-7,12345678901234567890]}`,
			`{"n":[0,-7,12345678901234567890]}`,
		},
		{
			"key order by code point",
			`{"k2":"b","k10":"a","K":"c","ключ":"d"}`,
			`{"K":"c","k10":"a","k2":"b","\u043a\u043b\u044e\u0447":"d"}`,
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			v, err := Decode([]byte(c.in))
			if err != nil {
				t.Fatalf("decode: %v", err)
			}
			got, err := Marshal(v)
			if err != nil {
				t.Fatalf("marshal: %v", err)
			}
			if string(got) != c.want {
				t.Fatalf("mismatch\n got: %s\nwant: %s", got, c.want)
			}
		})
	}
}

func TestMarshalRejectsNaN(t *testing.T) {
	if _, err := Marshal(map[string]any{"x": json.Number("NaN")}); err == nil {
		t.Fatal("NaN must be rejected")
	}
}

func TestDecodeRejectsTrailingData(t *testing.T) {
	if _, err := Decode([]byte(`{"a":1} {"b":2}`)); err == nil {
		t.Fatal("trailing data must be rejected")
	}
}

func TestMarshalNativeGoValues(t *testing.T) {
	got, err := Marshal(map[string]any{"z": int64(3), "a": 0.5, "m": []any{"s", false}})
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"a":0.5,"m":["s",false],"z":3}` {
		t.Fatalf("got %s", got)
	}
}
