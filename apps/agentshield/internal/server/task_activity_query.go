package server

import (
	"net/http"
	"net/url"
	"sort"
	"time"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

type activityQueryFilters struct {
	activityFilters
	From   string `json:"from"`
	To     string `json:"to"`
	Action string `json:"action"`
}

type activityQueryItem struct {
	taskActivityItem
	LastRecorded *string        `json:"last_recorded_at"`
	Decisions    map[string]int `json:"decisions"`
}

type activityQueryPage struct {
	taskActivityPage
	Filters activityQueryFilters `json:"filters"`
	Items   []activityQueryItem  `json:"items"`
}

func parseActivityQueryFilters(r *http.Request) (activityQuery, activityQueryFilters, bool) {
	values, err := url.ParseQuery(r.URL.RawQuery)
	f := activityQueryFilters{}
	if err != nil {
		return activityQuery{}, f, true
	}
	for name, target := range map[string]*string{"from": &f.From, "to": &f.To, "action": &f.Action} {
		if vv, ok := values[name]; ok {
			if len(vv) != 1 || len(vv[0]) > 64 {
				return activityQuery{}, f, true
			}
			*target = vv[0]
			values.Del(name)
		}
	}
	if f.Action != "" && f.Action != "allow" && f.Action != "deny" && f.Action != "hold" && f.Action != "redact" {
		return activityQuery{}, f, true
	}
	var from, to time.Time
	if f.From != "" {
		from, err = time.Parse(time.RFC3339Nano, f.From)
		if err != nil {
			return activityQuery{}, f, true
		}
	}
	if f.To != "" {
		to, err = time.Parse(time.RFC3339Nano, f.To)
		if err != nil || f.From != "" && !from.Before(to) {
			return activityQuery{}, f, true
		}
	}
	clone := r.Clone(r.Context())
	u := *r.URL
	u.RawQuery = values.Encode()
	clone.URL = &u
	q, base, invalid := parseActivitySearch(clone)
	f.activityFilters = base
	return q, f, invalid
}

func summarizeActivity(all []receipt.Receipt, item taskActivityItem, indexes []int) activityQueryItem {
	out := activityQueryItem{taskActivityItem: item, Decisions: map[string]int{"allow": 0, "deny": 0, "hold": 0, "redact": 0, "other": 0}}
	for _, index := range indexes {
		rc := all[index]
		if rc.RecordType != "" && rc.RecordType != "decision" {
			continue
		}
		action := rc.Action
		if _, ok := out.Decisions[action]; !ok {
			action = "other"
		}
		out.Decisions[action]++
	}
	if len(indexes) > 0 {
		if at, err := time.Parse(time.RFC3339Nano, all[indexes[len(indexes)-1]].IssuedAt); err == nil {
			value := at.UTC().Format(time.RFC3339Nano)
			out.LastRecorded = &value
		}
	}
	return out
}

func (f activityQueryFilters) includes(item activityQueryItem) bool {
	if f.Action != "" && item.Decisions[f.Action] == 0 {
		return false
	}
	if f.From == "" && f.To == "" {
		return true
	}
	if item.LastRecorded == nil {
		return false
	}
	at, _ := time.Parse(time.RFC3339Nano, *item.LastRecorded)
	from, _ := time.Parse(time.RFC3339Nano, f.From)
	to, _ := time.Parse(time.RFC3339Nano, f.To)
	return (f.From == "" || !at.Before(from)) && (f.To == "" || at.Before(to))
}

func (s *Server) taskActivityQuery(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	q, filters, invalid := parseActivityQueryFilters(r)
	if invalid {
		writeJSON(w, 400, map[string]string{"error": "task_activity_query_invalid"})
		return
	}
	all, projection, err := s.d.Engine.TaskActivitySnapshot()
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "task_activity_snapshot_unavailable"})
		return
	}
	projection = filterActivities(all, projection, filters.activityFilters)
	page := projectActivityPage(all, projection, q.view, 0, 1)
	if q.snapshot != "" && q.snapshot != page.Snapshot {
		writeJSON(w, 409, map[string]string{"error": "task_activity_snapshot_changed"})
		return
	}
	items := make([]activityQueryItem, 0)
	for i := 0; i < page.Total; i++ {
		base := projectActivityPage(all, projection, q.view, i, 1).Items[0]
		var indexes []int
		if q.view == "unassigned" {
			indexes = []int{projection.Unassigned[i]}
		} else {
			indexes = projection.Tasks[i].ReceiptIndexes
		}
		item := summarizeActivity(all, base, indexes)
		if filters.includes(item) {
			items = append(items, item)
		}
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Last > items[j].Last })
	page.Schema, page.Offset, page.Total, page.Next = "local-task-activity-query/v1", q.offset, len(items), nil
	start := q.offset
	if start > len(items) {
		start = len(items)
	}
	end := start + q.limit
	if end >= len(items) {
		end = len(items)
	} else {
		page.Next = &end
	}
	writeJSON(w, 200, activityQueryPage{taskActivityPage: page, Filters: filters, Items: items[start:end]})
}
