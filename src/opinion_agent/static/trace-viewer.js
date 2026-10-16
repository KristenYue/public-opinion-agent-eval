const form = document.querySelector("#trace-form");
const jobInput = document.querySelector("#job-id");
const apiKeyInput = document.querySelector("#api-key");
const resultPanel = document.querySelector("#trace-result");
const emptyPanel = document.querySelector("#trace-empty");
const errorPanel = document.querySelector("#trace-error");

const lifecycleLabels = {
  queued: "排队等待",
  running: "执行中",
  retrying: "等待恢复重试",
  degraded: "降级完成",
  manual_required: "暂停 · 等待人工复核",
  failed_closed: "失败关闭",
  completed: "已完成",
};

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value === null || value === undefined ? "" : String(value);
  return node.innerHTML;
}

function dateTime(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short", timeStyle: "medium", hour12: false,
  }).format(new Date(value));
}

function jsonSummary(value) {
  if (value === null || value === undefined) return "-";
  const encoded = JSON.stringify(value);
  return encoded.length > 240 ? `${encoded.slice(0, 240)}…` : encoded;
}

function renderCheckpoints(items) {
  if (!items.length) return '<div class="audit-none">暂无检查点</div>';
  return items.map((item) => `<div class="ledger-row">
    <span class="ledger-index">C${item.sequence_no}</span>
    <div><strong>${escapeHtml(item.checkpoint_kind)}</strong><small>${escapeHtml(item.node_name)} · ${dateTime(item.created_at)}</small></div>
    <code title="${escapeHtml(item.state_sha256)}">${escapeHtml(item.state_sha256.slice(0, 12))}</code>
  </div>`).join("");
}

function renderTools(items) {
  if (!items.length) return '<div class="audit-none">暂无已持久化工具调用</div>';
  return items.map((item) => `<div class="ledger-row">
    <span class="ledger-index">T${item.sequence_no}</span>
    <div><strong>${escapeHtml(item.node_name)} · ${escapeHtml(item.tool_name)}</strong><small>${escapeHtml(item.status)} · ${Number(item.duration_ms || 0).toFixed(2)} ms</small></div>
    <code>${escapeHtml(jsonSummary(item.response_payload || item.request_payload))}</code>
  </div>`).join("");
}

function renderRuns(runs) {
  document.querySelector("#run-count").textContent = `${runs.length} 次尝试`;
  document.querySelector("#run-list").innerHTML = runs.length ? runs.map((run) => `<article class="run-card">
    <header>
      <div><span class="attempt-mark">尝试 ${run.attempt}</span><strong>${escapeHtml(run.status)}</strong></div>
      <code>${escapeHtml(run.trace_id)}</code>
    </header>
    <dl class="run-meta">
      <div><dt>Worker</dt><dd>${escapeHtml(run.worker_id || "-")}</dd></div>
      <div><dt>开始</dt><dd>${dateTime(run.started_at)}</dd></div>
      <div><dt>结束</dt><dd>${dateTime(run.finished_at)}</dd></div>
      <div><dt>Token</dt><dd>${run.token_input} → ${run.token_output}</dd></div>
    </dl>
    ${run.recovery_reason ? `<div class="recovery-reason"><strong>恢复原因</strong>${escapeHtml(run.recovery_reason)}</div>` : ""}
    <details open><summary>检查点 · ${run.checkpoints.length}</summary>${renderCheckpoints(run.checkpoints)}</details>
    <details><summary>工具调用 · ${run.tool_calls.length}</summary>${renderTools(run.tool_calls)}</details>
  </article>`).join("") : '<div class="audit-none standalone">任务尚未被 Worker 领取。</div>';
}

function renderReviews(items) {
  document.querySelector("#review-list").innerHTML = items.length ? items.map((item) => `<article class="side-item">
    <strong>${escapeHtml(item.final_label)}</strong>
    <span>${escapeHtml(item.reviewer_id)} · ${dateTime(item.submitted_at)}</span>
    <p>${escapeHtml(item.rationale || "未填写说明")}</p>
  </article>`).join("") : '<div class="audit-none">暂无人工复核记录</div>';
}

function renderShadows(items) {
  document.querySelector("#shadow-list").innerHTML = items.length ? items.map((item) => `<article class="side-item">
    <strong>${escapeHtml(item.candidate_name)}</strong>
    <span>${escapeHtml(item.status)} · ${Number(item.duration_ms).toFixed(2)} ms</span>
    <p>${escapeHtml(item.error_message || "结果保持隔离，未改写正式状态")}</p>
  </article>`).join("") : '<div class="audit-none">Shadow 默认关闭或暂无记录</div>';
}

function renderTrace(trace) {
  const job = trace.job;
  document.querySelector("#job-event").textContent = job.event_id;
  document.querySelector("#job-identity").textContent = job.id;
  const badge = document.querySelector("#job-status");
  badge.textContent = job.status;
  badge.className = `lifecycle-badge status-${job.status}`;
  document.querySelector("#attempt-count").textContent = job.attempt_count;
  document.querySelector("#recovery-count").textContent = job.recovery_count;
  document.querySelector("#lifecycle-label").textContent = lifecycleLabels[job.status] || job.status;
  document.querySelector("#updated-at").textContent = dateTime(job.updated_at);
  const failure = document.querySelector("#failure-panel");
  failure.hidden = !job.error_code && !job.error_message;
  document.querySelector("#failure-code").textContent = job.error_code || "运行提示";
  document.querySelector("#failure-message").textContent = job.error_message || "";
  renderRuns(trace.runs);
  renderReviews(trace.human_reviews);
  renderShadows(trace.shadow_runs);
  emptyPanel.hidden = true;
  resultPanel.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorPanel.hidden = true;
  const jobId = jobInput.value.trim();
  const apiKey = apiKeyInput.value;
  if (!apiKey) {
    errorPanel.textContent = "请输入具备该 Project 权限的 V2 API Token。";
    errorPanel.hidden = false;
    return;
  }
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(jobId)) {
    errorPanel.textContent = "请输入标准 UUID 格式的 Job ID。";
    errorPanel.hidden = false;
    return;
  }
  const button = form.querySelector("button");
  button.disabled = true;
  button.textContent = "读取中";
  try {
    const response = await fetch(`/v2/jobs/${encodeURIComponent(jobId)}/trace`, {
      headers: { "X-API-Key": apiKey },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(response.status === 401 ? "Token 无效或缺失。" : response.status === 403 ? "你没有读取此 Project 审计记录的权限。" : response.status === 404 ? "未找到该任务。" : (body.detail || `读取失败：${response.status}`));
    }
    renderTrace(await response.json());
    history.replaceState(null, "", `/trace?job_id=${encodeURIComponent(jobId)}`);
  } catch (error) {
    errorPanel.textContent = error.message || "审计轨迹读取失败。";
    errorPanel.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "读取审计轨迹";
  }
});

const initialJobId = new URLSearchParams(location.search).get("job_id");
if (initialJobId) {
  jobInput.value = initialJobId;
  form.requestSubmit();
}
