// Load test against the real path: create a workspace, upload a policy,
// run the analysis, poll until a brief exists.
//
// Run against replay mode (MERIDIAN_REPLAY=1), never the live provider. A
// load test pointed at a paid, rate-limited API measures that API's queue,
// not this pipeline — and burns quota to learn nothing. `make bench-load`
// sets it up.
//
//   k6 run loadtest/upload_to_brief.js
//
// Thresholds are ABORT conditions, not targets. They exist so a run that has
// already gone wrong stops early instead of producing numbers nobody should
// quote.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate, Counter } from "k6/metrics";

const BASE = __ENV.BASE_URL || "http://localhost:8000";
const PDF_PATH = __ENV.PDF_PATH || "./fixtures/sample-policy.pdf";

// One trend per stage, so the report says WHICH stage dominates rather than
// only how long the whole thing took.
const uploadTime = new Trend("meridian_upload_ms", true);
const runTriggerTime = new Trend("meridian_run_trigger_ms", true);
const analysisTime = new Trend("meridian_analysis_ms", true);
const endToEnd = new Trend("meridian_end_to_end_ms", true);

const analysisSucceeded = new Rate("meridian_analysis_success");
const capacityRejections = new Counter("meridian_capacity_rejections");

const pdf = open(PDF_PATH, "b");

export const options = {
  scenarios: {
    // Ramping rather than a fixed rate: the interesting number is where
    // admission control starts refusing, and a flat load never finds it.
    ramp: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "30s", target: 2 },
        { duration: "60s", target: 5 },
        { duration: "30s", target: 0 },
      ],
      gracefulRampDown: "30s",
    },
  },
  thresholds: {
    // A 429 from admission control is CORRECT behaviour under load, so it
    // must not count as a failure. Only 5xx and timeouts do.
    "http_req_failed{expected_response:true}": ["rate<0.05"],
    meridian_end_to_end_ms: ["p(95)<600000"],
  },
};

function jsonPost(path, body) {
  return http.post(`${BASE}${path}`, JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

export function setup() {
  // Fail fast and loudly rather than producing a run of 100% errors that
  // looks like a performance result.
  const ready = http.get(`${BASE}/healthz`);
  if (ready.status !== 200) {
    throw new Error(`API not reachable at ${BASE} (healthz ${ready.status})`);
  }
  return {};
}

export default function () {
  const started = Date.now();

  const created = jsonPost("/api/v1/workspace", {
    country: `LoadTest-${__VU}-${__ITER}`,
    policy_title: "Load test policy",
  });
  if (!check(created, { "workspace created": (r) => r.status === 200 })) {
    return;
  }
  const workspaceId = created.json("id");

  const t0 = Date.now();
  const uploaded = http.post(
    `${BASE}/api/v1/upload/${workspaceId}`,
    { file: http.file(pdf, "policy.pdf", "application/pdf") },
  );
  uploadTime.add(Date.now() - t0);
  if (!check(uploaded, { "upload accepted": (r) => r.status === 200 })) {
    return;
  }

  const t1 = Date.now();
  const run = http.post(`${BASE}/api/v1/analyze/${workspaceId}/run`);
  runTriggerTime.add(Date.now() - t1);

  // 429 is the server correctly refusing work it cannot do. Counted
  // separately so it is visible without polluting the error rate.
  if (run.status === 429) {
    capacityRejections.add(1);
    analysisSucceeded.add(false);
    sleep(2);
    return;
  }
  if (!check(run, { "run started": (r) => r.status === 200 })) {
    analysisSucceeded.add(false);
    return;
  }

  const t2 = Date.now();
  let done = false;
  for (let i = 0; i < 300 && !done; i++) {
    sleep(1);
    const poll = http.get(`${BASE}/api/v1/analyze/${workspaceId}`);
    if (poll.status !== 200) continue;
    const analyses = poll.json("analyses");
    if (analyses && analyses.length > 0) {
      done = true;
    }
  }
  analysisTime.add(Date.now() - t2);
  analysisSucceeded.add(done);

  if (done) {
    endToEnd.add(Date.now() - started);
  }
}
