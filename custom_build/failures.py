"""The failure module. So far: the catalog of codes (ARCHITECTURE.md section 6.1; rules F1 and F6).

The recording helper and the two wrappers are not written yet. tests/test_failures.py holds the catalog
to the table in ARCHITECTURE.md 6.1.
"""

# Every code an event can carry, with a short form of what it means; the table in ARCHITECTURE.md 6.1
# is the full meaning. A text that starts "Not a failure" marks an event that is recorded but is not a
# failure: it has no severity. tests/test_failures.py holds that mark to the table's.
CATALOG = {
    "embed.unavailable": "The embedding service cannot be reached",
    "embed.refused": "The hosted embedding service refuses the key: revoked, out of credit or not allowed",
    "embed.model_mismatch": "This machine's embedding build differs from the one recorded in the store",
    "db.unreachable": "The memory store cannot be reached",
    "db.auth": "The memory store refuses the role",
    "db.query": "The memory store rejects a query",
    "db.behind": "The memory store is behind the migrations the plugin needs",
    "recall.timeout": "Recall misses its deadline",
    "judge.timeout": "The judge model times out",
    "judge.error": "The judge model errors",
    "rerank.fallback": "The judge could not rerank, and the pool kept its fused order (degraded)",
    "action.skipped": "Not a failure: the action query was skipped, because the message asks for no work",
    "store.gate_error": "The judge failed during a write; the fact is queued, or dropped when the judge refuses the request",
    "extract.error": "The extraction model failed or answered something other than a list of facts",
    "extract.refused": "The extraction model's provider refused the account: logged out, billing, or forbidden",
    "digest.error": "The digest model failed or answered something other than a digest",
    "digest.refused": "The digest model's provider refused the account: logged out, billing, or forbidden",
    "digest.dropped": "Not a failure: a session's digest was not stored, because the judge did not keep it, or a later or concurrent digest of the session is live",
    "guard.bypassed": "A local session ran in safe mode or with the profile's settings ignored, or its launch policy cannot be read",
    "guard.crash": "A guard raised during a turn",
    "guard.not_loaded": "A guard's hooks or the provider were found not loaded",
    "write_gate.requested": "Not a failure: the write gate sent a call on its list to a person for approval",
    "write_gate.blocked": "Not a failure: the write gate blocked a call on its list before prompting",
    "write_gate.approved": "Not a failure: a person approved the call once",
    "write_gate.always": "Not a failure: a person approved the call and its like from now on",
    "write_gate.denied": "Not a failure: a person refused the call",
    "write_gate.unanswered": "Not a failure: nobody answered the approval request",
    "write_gate.would_ask": "Not a failure: in log mode, the write gate saw a call on its list that on would send for approval",
    "write_gate.would_block": "Not a failure: in log mode, the write gate saw a call on its list that on would block outright",
    "verify_gate.blocked": "Not a failure: the verify gate blocked a change to a listed file or setting the session never read",
    "verify_gate.withheld": "Not a failure: the verify gate withheld a reply that stated a listed file's contents the session never read",
    "verify_gate.would_block": "Not a failure: in log mode, a call would change a listed file or setting the session never read",
    "verify_gate.would_withhold": "Not a failure: in log mode, a reply stated a listed file's contents the session never read",
    "fact_gate.armed": "Not a failure: the user asked a checkable question",
    "fact_gate.would_withhold": "Not a failure: in log mode, a checkable question's reply lacked a required lookup",
    "fact_gate.withheld": "Not a failure: the fact gate withheld a reply that lacked a required lookup",
    "fact_gate.passed": "Not a failure: a checkable question's reply met the lookup rules",
    "recall_gate.armed": "Not a failure: in log mode, the user asked about past work or open work",
    "recall_gate.would_withhold": "Not a failure: in log mode, a past-work question's reply came without both the memory search and the session search",
    "recall_gate.passed": "Not a failure: in log mode, a past-work question's reply came with both searches",
    "config.unsafe": "A Hermes setting has a value the build does not support",
    "config.missing": "A setting the build needs is missing or invalid",
    "redact.failed": "The redactor raised; the text is not stored or sent",
    "memory.write_rejected": "Hermes refused a built-in memory write",
    "events.write_failed": "An events row could not be written; logged locally at ERROR",
    "job.failed": "A scheduled job failed or the startup check crashed",
    "job.missed": "A scheduled job did not run",
    "job.no_output": "A scheduled job took input and produced nothing",
    "job.succeeded": "Not a failure: a scheduled job's run finished; detail holds job and, where it has them, input and output",
    "host.missing": "An agent host on the job-health check's list wrote no heartbeat in the last 24 hours",
    "host.heartbeat": "Not a failure: an agent host's heartbeat job ran",
    "unhandled": "Anything not in the catalog, outside a guard, recorded with a sanitized diagnostic",
}

# Each failure code's severity. High: the build's protection or its record is gone. Medium: one answer
# or write is worse or delayed. Low: degraded, and the answer still came.
SEVERITY = {
    "embed.unavailable": "medium",
    "embed.refused": "high",   # every recall and store fails until the maintainer fixes the key
    "embed.model_mismatch": "high",
    "db.unreachable": "high",
    "db.auth": "high",
    "db.query": "medium",
    "db.behind": "high",
    "recall.timeout": "medium",
    "judge.timeout": "medium",
    "judge.error": "medium",
    "rerank.fallback": "low",
    "store.gate_error": "medium",
    "extract.error": "medium",
    "extract.refused": "high",
    "digest.error": "medium",
    "digest.refused": "high",
    "guard.bypassed": "high",
    "guard.crash": "high",
    "guard.not_loaded": "high",
    "config.unsafe": "high",
    "config.missing": "high",
    "redact.failed": "high",
    "memory.write_rejected": "medium",
    "events.write_failed": "high",
    "job.failed": "high",
    "job.missed": "high",
    "job.no_output": "medium",
    "host.missing": "high",
    "unhandled": "high",
}

# The codes the build shows in a turn. None yet: no code that runs in a turn is written.
SHOWN_IN_TURN = frozenset()
