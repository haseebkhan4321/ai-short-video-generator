# The task queue

Approved steps run in a Celery worker, not in the web process.

```bash
redis-server
celery -A config worker -l info --pool=threads --concurrency=4
python manage.py queue_status      # is it working?
```

On Windows the default prefork pool does not work — use `--pool=threads` (or
`--pool=solo` for one task at a time).

## What this replaced, and why

Every approved step used to run in a `threading.Thread(daemon=True)` inside the web
process. That meant:

- a 40-minute render died with `runserver`, halfway through, with no record of why
- no visibility: progress existed only for whoever had the page open
- the web process did the encoding, so a render competed with serving requests
- no way to limit concurrency, so approving twelve parts started twelve renders

Steps are tasks now. The step's own status doubles as queue state:

| Status | Means |
|---|---|
| `pending_approval` | waiting for a human |
| `approved` | authorized, queued, waiting for a worker to claim it |
| `running` | a worker has claimed it |
| `completed` / `failed` | done |

## One seam

`PipelineService.enqueue(step_ids)` is the only place work leaves a request. That
makes it the only place to mock in tests, and the only place a dead broker has to be
handled. Nine call sites used to start threads or run steps inline; they all go
through it.

## The claim is a compare-and-swap

`StepRepository.claim` is an `UPDATE ... WHERE status = 'approved'` and only the caller
whose update matched a row runs the step:

```python
changed = GenerationStep.objects.filter(
    pk=step_id, status=StepStatus.APPROVED
).update(status=StepStatus.RUNNING, started_at=timezone.now())
```

This is not defensive padding. The same step really can be enqueued twice — two page
loads both calling `resume_waiting_steps` is enough — and **running a paid step twice
charges twice**. A read-then-write would race; this cannot.

## No automatic retry

Deliberate. A step that failed partway through a paid OpenAI call may already have been
billed for, so retrying it unattended risks paying twice for the same work. Failures
surface on the video detail page with the provider's error, and the existing Retry
button is how they are re-run — by a person who can see what happened.

`CELERY_TASK_ACKS_LATE` is off for the same reason: with it on, a worker that dies
mid-task has the task redelivered, which is a retry by another name.

## The cost of that choice, and the fix

A worker killed mid-step leaves it `running` forever, because nothing will redeliver
it. That is the price of never double-charging.

```bash
python manage.py unstick_steps --older-than 180 --dry-run
python manage.py unstick_steps --older-than 180
```

It marks abandoned steps `failed` — never back to `approved`, because auto-re-running a
paid step is exactly what the design avoids. The decision to retry stays with a person.
Keep `--older-than` generous: a full render legitimately takes hours.

## One step, one task

`_advance` queues the next step rather than calling it inline. Chaining a render onto
the end of a narration inside one task would hold a single worker slot for the sum of
both, hide the second step's progress behind the first, and put both under one timeout.

## When the broker is down

| Where | Behaviour |
|---|---|
| Approving from the UI | `QueueUnavailableError`, and the message says the step stays approved and will start once the queue is back |
| `resume_waiting_steps` (runs on every page view) | swallowed — failing a page over a background retry is the wrong trade; the next page view tries again |
| `_advance` queueing follow-on work | swallowed — the predecessor genuinely succeeded, so failing it would be a lie |

In all three the step is left `approved`, which is honestly what it is: authorized but
not started. That is also exactly the state `resume_waiting_steps` looks for, so the
work resumes on its own.

## Settings

All under the `CELERY_` namespace in `config/settings/base.py`, driven by `.env`.

| Setting | Default | Why |
|---|---|---|
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Broker |
| `CELERY_RESULT_BACKEND` | `None` | Every piece of state the UI needs already lives on `GenerationStep`, and the page polls the database. A second store would be a second source of truth. |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | Steps are long and unevenly sized; prefetching would leave a queue stuck behind one slow render |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `14400` (4h) | A two-hour render is a normal task here |
| `CELERY_BROKER_TRANSPORT_OPTIONS` | `max_retries: 1` | Fail fast when enqueueing from a request — the user is waiting |

## redis-py is pinned below 6

`redis>=5,<6`. redis-py 6+ negotiates RESP3 with a `HELLO` handshake, and Redis server
5.x answers `unknown command 'HELLO'`. Laragon ships 5.0.14, so the client is capped.
Raise the cap only alongside a Redis 6+ server.

## Tests

`apps/videos/tests/test_queue.py`, 29 tests. The broker is never contacted: `enqueue`
is the seam, so mocking it covers everything around it, and the tasks are called
directly.

Covered: dispatch, the claim guard (including that a duplicate delivery runs nothing),
what each caller does when the broker is down, that `_advance` queues rather than runs
inline, that a failing executor is contained to its own step, and both management
commands.
