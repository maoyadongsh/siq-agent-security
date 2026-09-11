package receipt

import "testing"

func TestFileAliasesCannotBypassGrantedWriteScope(t *testing.T) {
	for _, tool := range []string{"write", "edit", "remove"} {
		t.Run(tool, func(t *testing.T) {
			g := deployedGrant(t, "hermes", false)
			allowed := append(*g.HermesToolsetAllowlist, tool)
			g.HermesToolsetAllowlist = &allowed
			fx := newFixture(t, "block", g, false)
			d, err := fx.eng.Decide(req("hermes", tool, map[string]any{"path": "/secret/report"}))
			if err != nil || d.Action != ActionDeny {
				t.Fatal("alias bypassed filesystem policy", d, err)
			}
			d, err = fx.eng.Decide(req("hermes", tool, map[string]any{"path": "/home/u/work/out/report"}))
			if err != nil || d.Action != ActionAllow {
				t.Fatal("explicitly granted path lost compatibility", d, err)
			}
		})
	}
}
