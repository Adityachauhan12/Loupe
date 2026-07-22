# Design — Kafka trace-ingestion pipeline (learning/scale-out track)

> **Status:** 🔵 DESIGN ONLY — no code yet. This documents the *why* and the *how*
> so the decisions can be defended in an interview before anything is built.
>
> **One-liner:** Move trace/span ingestion off the synchronous HTTP→Postgres path
> onto a durable Kafka log with a consumer group that batch-writes to Postgres —
> the canonical decoupled-ingestion pattern real telemetry backends use.

---

## 1. Why — the tension

Loupe is a telemetry pipeline. Today the write path is:

```
SDK ──POST /v1/traces──▶ FastAPI ──synchronous INSERT──▶ Postgres
```

The ingest endpoint validates the payload and writes it to Postgres *inside the
request*. That couples three things that want to move independently:

- **ingest rate** (bursty — an agent under load emits spans in spikes),
- **write rate** (Postgres throughput, which degrades under contention), and
- **availability** (if Postgres is slow or down, ingestion stalls or *drops data*).

At demo scale this is correct and simple (see locked decision **A5** — we keep
things minimal until scale justifies otherwise). This design is what we'd reach
for when ingest volume is the bottleneck — and, more honestly here, it's the
place where adding a distributed log is *legitimate* rather than contrived,
because ingestion decoupling is a real, well-known pattern for exactly this
domain.

**Explicit scope note.** The MVP guardrails (CLAUDE.md) list extra data stores as
BRUTALLY OUT and commit to light, self-hostable infra. Kafka is heavier than that
rule allows. So this is a *deliberate, opt-in* expansion: the default ingestion
path stays HTTP→Postgres; Kafka is a feature-flagged mode. We honor the guardrail
by not making it the default and not breaking the light `docker-compose`.

---

## 2. Target architecture

```
                       produce                     consume (group)
SDK ─POST─▶ FastAPI ───────────▶ Kafka topic ───────────────────▶ consumer worker ─▶ Postgres
            (producer)          `loupe.traces`                    (batch, idempotent)
              │                  partitioned by project_id              │
         returns 202                durable buffer               bulk upsert
```

- **Producer** = the `/v1/traces` endpoint. Its only job becomes: validate →
  publish → return `202 Accepted`. It no longer touches Postgres.
- **Topic** = `loupe.traces`, partitioned. The durable buffer.
- **Consumer group** = one or more worker processes (`server/app/consumer.py`)
  that read, batch, and bulk-upsert into Postgres.

The read side of Loupe is unchanged: the dashboard, replay, and suites all still
read from Postgres. Only the write path is re-routed. **The North Star demo is
untouched.**

---

## 3. Topic & partitioning design

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Topic name | `loupe.traces` | One event = one trace+its spans batch (the SDK already flushes a trace as one payload). |
| Partition key | `project_id` | All events for a project land on one partition → **ordering within a project**, and parallelism **across** projects. Never key by `trace_id` (too many keys, no ordering benefit). |
| Partition count | start 3–6 | Partition count caps consumer parallelism. Pick a few now; increasing later is possible but reshuffles keys. |
| Retention | e.g. 7 days | The log doubles as a short-term durable buffer + replay source (rebuild the DB, or feed a future second sink like ClickHouse). |
| Serialization | JSON (MVP) | Simple, matches existing Pydantic wire schema. **Tradeoff:** Avro + Schema Registry gives schema evolution + smaller payloads; overkill now, name it in interviews. |

---

## 4. Delivery semantics — the key decision

**Chosen: at-least-once delivery + idempotent consumer.**

Kafka's practical default is at-least-once: a message can be redelivered (e.g. a
consumer crashes after writing but before committing its offset). That's normally
a headache — but Loupe already solved it via locked decision **A3: the SDK
generates trace/span UUIDs**. So the consumer does an **idempotent upsert**
(`INSERT ... ON CONFLICT (id) DO NOTHING/UPDATE`). A redelivered message re-writes
the same rows → no duplicates, no corruption.

> **Interview line:** "Client-generated IDs let me pair at-least-once delivery
> with idempotent upserts, so I get correctness without paying for Kafka's
> exactly-once machinery (transactional producer + read-committed consumer),
> which is complex and slower."

Why not exactly-once? It requires transactional writes spanning Kafka offsets +
the DB (or the idempotent-producer + transactions path). More moving parts for a
guarantee we already get more cheaply thanks to A3.

---

## 5. Offset-commit strategy (where at-least-once actually comes from)

Commit offsets **after** the batch is durably written to Postgres, never before:

```
poll batch ─▶ bulk upsert to Postgres ─▶ (success) commit offsets
                                    └▶ (failure) do NOT commit → redelivered next poll
```

- Disable auto-commit. Commit manually post-write.
- Crash after write, before commit → redelivery → idempotent upsert absorbs it. ✅
- This is the concrete mechanism behind "at-least-once": offsets follow durable
  writes, so nothing is acked until it's safely stored.

---

## 6. Failure modes & how each is handled

| Failure | Behaviour | Why it's safe |
|---------|-----------|----------------|
| Postgres down | Consumer stops committing; events pile up **durably in Kafka**. | No data loss, no ingest stall. Ingest endpoint still 202s. This is the headline durability win. |
| Consumer crashes mid-batch | Uncommitted offsets → partition reassigned, batch redelivered. | Idempotent upsert (A3) makes redelivery a no-op. |
| Consumer group scales up/down | Kafka **rebalances** partitions across members. | Consumer-group mechanics; per-partition ordering preserved. |
| Poison message (unparseable) | Route to a **dead-letter topic** `loupe.traces.dlq` after N retries. | Don't block the partition on one bad event. |
| Producer can't reach Kafka | Endpoint returns 5xx; SDK's existing retry/backoff kicks in. | The SDK already batches + retries on flush. |

---

## 7. Observability — the one metric that matters

**Consumer lag** = (latest offset produced) − (latest offset committed). It's the
single best health signal: rising lag = consumers can't keep up with ingest.
Expose it (JMX / `kafka-consumer-groups` / a Prometheus exporter). In an
interview, "I watched consumer lag" signals you actually operated the thing.

Secondary: partition skew (is one `project_id` hot-spotting a partition?),
DLQ rate.

---

## 8. Local dev & config

- **`docker-compose`**: add a single-broker Kafka in **KRaft mode** (no ZooKeeper —
  modern, one container) under an **opt-in profile** so the default `up` stays
  light.
- **Feature flag**: `LOUPE_INGEST_MODE = direct | kafka` (default `direct`).
  - `direct` → today's synchronous write (unchanged).
  - `kafka` → endpoint publishes; consumer worker does the write.
- New process: `python -m app.consumer` (its own container/entrypoint).

---

## 9. Testing strategy (so CI needs no real broker)

- **Producer unit tests**: inject a fake producer; assert the endpoint publishes
  the right key (`project_id`) + payload and returns 202 without touching the DB.
- **Consumer unit tests**: feed a list of fake messages to the batch-upsert
  function; assert idempotency (feed the same message twice → one row) and DLQ
  routing on a poison message.
- **Integration (optional, not in default CI)**: `testcontainers` spins a real
  broker for one end-to-end test. Keep it out of the fast CI lane.

---

## 10. Tradeoffs — the honest summary

**Wins:** durability + backpressure absorption, ingest/write decoupling,
horizontal consumer scale, log replayability (rebuild DB or fan out to a second
sink), a correctness story (A3 → idempotent at-least-once).

**Costs:** a broker to run and monitor; eventual consistency (a trace is
queryable a beat after it's accepted, not instantly); more operational surface
(lag, rebalances, DLQ). For MVP scale it's over-provisioned — which is why it's
**opt-in, not default**.

---

## 11. Why NOT to put Kafka elsewhere in Loupe (so you can rebut it)

- **Suite runs / replay jobs** (the A5 space): Kafka is a *log*, not a task queue.
  No per-message ack, visibility timeout, or retry semantics like Celery/SQS.
  Using it here would be *marked down*. A5 already names Celery+Redis as the
  correct scale answer. **Leave it.**
- **Realtime dashboard streaming**: explicitly OUT of scope (polling is fine).
  Kafka→WebSocket would be contrived here.

Ingestion is the one right home.

---

## 12. Build plan (phased — execute later, no code yet)

1. **Infra**: `docker-compose` KRaft broker under a `kafka` profile; create
   `loupe.traces` (+ `.dlq`) topics on startup.
2. **Config**: add `LOUPE_INGEST_MODE`, broker URL, topic names to settings.
3. **Producer**: refactor `/v1/traces` to publish when mode=`kafka` (keep the
   `direct` branch as today). Serialize the existing Pydantic payload; key by
   `project_id`.
4. **Consumer**: `app/consumer.py` — poll, batch, idempotent bulk upsert, manual
   offset commit post-write, DLQ on poison. Reuse the existing SQLAlchemy models.
5. **Tests**: fake-producer + fake-consumer unit tests (above).
6. **Docs**: promote the locked choices into `ARCHITECTURE_DECISIONS.md` as a new
   `A#` entry; note the A3 synergy explicitly.
7. **Ops**: expose consumer lag; a one-paragraph runbook.

---

## 13. Interview Q&A prep (rehearse these)

- *Why Kafka and not a queue (RabbitMQ/SQS)?* — Durable, replayable log + high
  fan-out throughput; I want the buffer to double as a replay source and future
  multi-sink, not just a work queue.
- *How do you avoid duplicates?* — At-least-once + idempotent upsert on
  client-generated UUIDs; offsets committed only after durable writes.
- *Why exactly-once not needed?* — A3 gives idempotency for free; EoS adds
  transactional cost for no extra correctness here.
- *How do you scale consumers?* — Consumer group; add members up to partition
  count; Kafka rebalances. Partition count is the parallelism ceiling.
- *What's your health metric?* — Consumer lag (and partition skew, DLQ rate).
- *What breaks if Postgres is down?* — Nothing is lost; events buffer in Kafka;
  ingest still 202s; lag rises and drains when the DB returns.
- *Ordering guarantees?* — Per-partition (per-`project_id`) ordering only; no
  global order, which we don't need.
