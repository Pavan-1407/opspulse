def _first_unassigned(client):
    r = client.get("/api/tickets", params={"unassigned": True})
    assert r.status_code == 200
    assert r.json(), "seed should leave an unassigned queue"
    return r.json()[0]


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_open_queue_is_scored(client):
    rows = client.get("/api/tickets").json()
    assert rows
    for t in rows:
        assert 0.0 <= t["sla_risk"] <= 1.0
        assert t["risk_band"] in {"low", "medium", "high", "breached"}
    risks = [t["sla_risk"] for t in rows]
    assert risks == sorted(risks, reverse=True)


def test_ticket_detail_has_explanations_and_recommendations(client):
    t = _first_unassigned(client)
    d = client.get(f"/api/tickets/{t['id']}").json()
    assert len(d["recommendations"]) == 3
    assert d["drivers"], "SHAP drivers expected for an open, not-yet-due ticket"
    scores = [r["score"] for r in d["recommendations"]]
    assert scores == sorted(scores)


def test_assign_timer_lifecycle(client):
    t = _first_unassigned(client)
    rec = client.get(f"/api/tickets/{t['id']}").json()["recommendations"][0]
    a = rec["analyst_id"]
    assert client.post(f"/api/tickets/{t['id']}/assign", json={"analyst_id": a}).json()["status"] == "ASSIGNED"

    timer = client.post("/api/timers/start", json={"analyst_id": a, "ticket_id": t["id"]}).json()
    assert timer["ended_at"] is None
    # idempotent: starting the same ticket again returns the running timer
    again = client.post("/api/timers/start", json={"analyst_id": a, "ticket_id": t["id"]}).json()
    assert again["id"] == timer["id"]
    # only the assignee can time a ticket
    other = next(x["id"] for x in client.get("/api/analysts").json() if x["id"] != a)
    assert client.post("/api/timers/start", json={"analyst_id": other, "ticket_id": t["id"]}).status_code == 409

    closed = client.post(f"/api/tickets/{t['id']}/status", json={"status": "CLOSED"}).json()
    assert closed["status"] == "CLOSED"
    running = [x for x in client.get("/api/timers/active").json() if x["analyst_id"] == a]
    assert not running, "closing a ticket stops its timer"


def test_switching_tickets_stops_previous_timer(client):
    rows = client.get("/api/tickets").json()
    by_analyst = {}
    for t in rows:
        if t["assigned_to"] and t["status"] in ("ASSIGNED", "IN_PROGRESS"):
            by_analyst.setdefault(t["assigned_to"], []).append(t["id"])
    a, ids = next((k, v) for k, v in by_analyst.items() if len(v) >= 2)
    first = client.post("/api/timers/start", json={"analyst_id": a, "ticket_id": ids[0]}).json()
    second = client.post("/api/timers/start", json={"analyst_id": a, "ticket_id": ids[1]}).json()
    running = [x for x in client.get("/api/timers/active").json() if x["analyst_id"] == a]
    assert [x["id"] for x in running] == [second["id"]]
    assert first["id"] != second["id"]


def test_auto_balance_respects_capacity(client):
    plan = client.get("/api/ml/auto-balance", params={"max_open": 6}).json()
    loads = {a["id"]: a["open_tickets"] for a in client.get("/api/analysts").json()}
    added = {}
    for p in plan:
        added[p["analyst_id"]] = added.get(p["analyst_id"], 0) + 1
    for a, n in added.items():
        assert loads[a] + n <= 6
    assert len({p["ticket_id"] for p in plan}) == len(plan)


def test_create_and_upload(client):
    r = client.post("/api/tickets", json={"title": "Manual ticket", "work_type_code": "RECON", "priority": "P1"})
    assert r.status_code == 201 and r.json()["status"] == "NEW"
    assert client.post("/api/tickets", json={"title": "x" * 5, "work_type_code": "BAD"}).status_code == 422

    csv = (
        "external_ref,title,work_type,priority,channel,complexity,line_items\n"
        "UP-1,Upload ok,DATA_FIX,P2,email,2,3\n"
        "UP-2,Bad type,NOPE,P2,email,1,1\n"
        "UP-1,Duplicate,DATA_FIX,P3,email,1,1\n"
    )
    rep = client.post("/api/tickets/upload", files={"file": ("t.csv", csv, "text/csv")}).json()
    assert rep["inserted"] == 1 and rep["rejected"] == 2


def test_upload_rejects_missing_columns(client):
    r = client.post("/api/tickets/upload", files={"file": ("t.csv", "title\nx\n", "text/csv")})
    assert r.status_code == 422


def test_kpis_and_forecast(client):
    k = client.get("/api/kpis/overview").json()
    assert k["kpis"]["open_backlog"] > 0
    assert 0 <= k["kpis"]["sla_attainment_30d"] <= 1
    f = client.get("/api/forecast").json()
    assert len(f["forecast"]) == 28
    assert all(x["lower"] <= x["forecast"] <= x["upper"] for x in f["forecast"])
    assert f["backtest"]["holt_winters_wape"] < f["backtest"]["seasonal_naive_wape"]


def test_model_card_beats_baseline(client):
    m = client.get("/api/ml/model-card").json()
    assert m["roc_auc"] > 0.75
    assert m["pr_auc"] > m["baseline"]["pr_auc"]
