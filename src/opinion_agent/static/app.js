const form = document.querySelector("#analysis-form");
const commentsInput = document.querySelector("#comments");
const countLabel = document.querySelector("#comment-count");
const runButton = document.querySelector("#run-analysis");
const loadDemoButton = document.querySelector("#load-demo");
const emptyState = document.querySelector("#empty-state");
const loadingState = document.querySelector("#loading-state");
const errorBanner = document.querySelector("#error-banner");
let latestResult = null;

const demo = {
  eventId: "关税",
  query: "分析关税事件评论，识别争议内容并检索历史相似事件",
  context: "相关政策调整引发公众对价格、就业和国际贸易影响的讨论。",
  sourceUrl: "https://example.com/event/tariff",
  comments: [
    "普通消费者最后还是要承担更高成本",
    "先看看后续具体实施细则",
    "又变了",
    "这项调整对国内企业可能是机会",
    "政策一天一个样，完全看不懂",
  ],
};

function lines() {
  return commentsInput.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function updateCount() {
  countLabel.textContent = `${lines().length} 条`;
}

function setDemo() {
  document.querySelector("#event-id").value = demo.eventId;
  document.querySelector("#query").value = demo.query;
  document.querySelector("#context").value = demo.context;
  document.querySelector("#source-url").value = demo.sourceUrl;
  commentsInput.value = demo.comments.join("\n");
  updateCount();
}

function setLoading(active) {
  runButton.disabled = active;
  runButton.querySelector("span:last-child").textContent = active ? "研判执行中" : "运行研判";
  emptyState.hidden = true;
  loadingState.hidden = !active;
  document.querySelectorAll(".tab-view").forEach((view) => { view.hidden = true; });
}

function showError(message) {
  errorBanner.textContent = message;
  errorBanner.hidden = false;
}

function clearError() {
  errorBanner.hidden = true;
  errorBanner.textContent = "";
}

function percentage(value) {
  return `${((Number(value) || 0) * 100).toFixed(1)}%`;
}

function text(value, fallback = "-") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function totalLatency(traces) {
  return (traces || []).reduce((sum, item) => sum + (Number(item.duration_ms) || 0), 0);
}

function setAttention(level) {
  const badge = document.querySelector("#attention-badge");
  const labels = { High: "高关注", Medium: "中关注", Low: "低关注", Uncertain: "待复核" };
  badge.textContent = labels[level] || "未知";
  badge.className = `badge ${String(level || "neutral").toLowerCase()}`;
}

function renderSentiment(snapshot) {
  const labels = [
    ["Negative", "负面"], ["Neutral", "中性"], ["Positive", "正面"], ["Unscorable", "不可判定"],
  ];
  const proportions = snapshot?.proportions || {};
  document.querySelector("#sentiment-bars").innerHTML = labels.map(([key, label]) => {
    const value = Number(proportions[key]) || 0;
    return `<div class="sentiment-row">
      <span>${label}</span>
      <div class="sentiment-track"><div class="sentiment-fill ${key.toLowerCase()}" style="width:${value * 100}%"></div></div>
      <strong>${percentage(value)}</strong>
    </div>`;
  }).join("");
}

function renderReviewWarning(reviewStatus) {
  const warning = document.querySelector("#review-warning");
  const messages = {
    manual_required: "当前展示的是主模型原始情绪结果，尚未完成 LLM 或人工复核，不能作为最终研判结论。",
    llm_failed: "LLM 复核失败，当前展示的是主模型原始情绪结果；请人工复核后再形成最终结论。",
  };
  const message = messages[reviewStatus];
  warning.hidden = !message;
  warning.textContent = message || "";
}

function renderList(selector, items) {
  const element = document.querySelector(selector);
  element.innerHTML = (items?.length ? items : ["无"]).map((item) => `<li>${escapeHtml(text(item))}</li>`).join("");
}

function reviewReason(item) {
  if (item.label === "Unscorable") return "不可评分";
  if (item.models_agree === false) return "模型分歧";
  if ((item.text || "").trim().length <= 4) return "短文本";
  return "常规";
}

function renderReview(result) {
  const rows = (result.sentiment_results || []).filter((item) =>
    item.label === "Unscorable" || item.models_agree === false || (item.text || "").trim().length <= 4
  );
  document.querySelector("#review-count").textContent = `${rows.length} 条`;
  document.querySelector("#review-table").innerHTML = rows.length ? rows.map((item) => `<tr>
    <td>${escapeHtml(text(item.sample_id))}</td>
    <td class="cell-comment">${escapeHtml(text(item.text))}</td>
    <td><span class="model-label">${escapeHtml(text(item.label))}</span></td>
    <td>${escapeHtml(text(item.secondary_label))}</td>
    <td>${reviewReason(item)}</td>
  </tr>`).join("") : `<tr><td colspan="5" class="no-data">无评论级复核项</td></tr>`;

  const evidence = result.retrieved_evidence || [];
  document.querySelector("#evidence-count").textContent = `${evidence.length} 条`;
  document.querySelector("#evidence-list").innerHTML = evidence.length ? evidence.map((item) => `<article class="evidence-item">
    <strong>${escapeHtml(text(item.event_id))}</strong>
    <span>相关分 ${Number(item.score || 0).toFixed(4)} · ${escapeHtml(text(item.evidence_id))}</span>
    ${item.source_url ? `<a href="${escapeAttribute(item.source_url)}" target="_blank" rel="noreferrer">查看来源</a>` : ""}
  </article>`).join("") : `<div class="no-data">未接受历史事件证据</div>`;
}

function renderTrace(traces) {
  const list = traces || [];
  document.querySelector("#trace-list").innerHTML = list.length ? list.map((item, index) => `<div class="trace-item">
    <span class="trace-state ${escapeAttribute(item.status)}"></span>
    <span class="trace-node">${String(index + 1).padStart(2, "0")} · ${escapeHtml(text(item.node))}</span>
    <span class="trace-details">${escapeHtml(JSON.stringify(item.details || {}))}</span>
    <span class="trace-duration">${Number(item.duration_ms || 0).toFixed(2)} ms</span>
  </div>`).join("") : `<div class="no-data">无工具轨迹</div>`;
}

function renderResult(result) {
  latestResult = result;
  const report = result.analysis_report || {};
  const snapshot = report.sentiment_snapshot || result.aggregate_stats || {};
  loadingState.hidden = true;
  emptyState.hidden = true;
  document.querySelector("#result-title").textContent = text(report.event_id || result.event_id, "研判结果");
  document.querySelector("#request-id").textContent = text(result.request_id, "");
  document.querySelector("#executive-summary").textContent = text(report.executive_summary || result.final_report);
  document.querySelector("#metric-total").textContent = text(snapshot.total, "0");
  document.querySelector("#metric-disagreement").textContent = percentage(snapshot.model_disagreement_rate);
  document.querySelector("#metric-evidence").textContent = String((result.retrieved_evidence || []).length);
  document.querySelector("#metric-latency").textContent = `${totalLatency(result.tool_traces).toFixed(1)} ms`;
  document.querySelector("#review-status").textContent = `复核状态 · ${text(report.review_status)}`;
  renderReviewWarning(report.review_status);
  setAttention(report.attention_level);
  renderSentiment(snapshot);
  renderList("#risk-signals", report.risk_signals);
  renderList("#recommended-actions", report.recommended_actions);
  renderList("#limitations", report.limitations);
  renderReview(result);
  renderTrace(result.tool_traces);
  showTab("overview");
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".tab-view").forEach((view) => { view.hidden = view.id !== `${name}-view`; });
}

function escapeHtml(value) {
  const node = document.createElement("span");
  node.textContent = value;
  return node.innerHTML;
}

function escapeAttribute(value) {
  return escapeHtml(String(value)).replaceAll('"', "&quot;");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const commentLines = lines();
  if (!commentLines.length) {
    showError("请至少提供一条评论。");
    return;
  }
  const context = document.querySelector("#context").value.trim();
  const sourceUrl = document.querySelector("#source-url").value.trim();
  const payload = {
    event_id: document.querySelector("#event-id").value.trim(),
    query: document.querySelector("#query").value.trim(),
    comments: commentLines.map((comment, index) => ({
      sample_id: `comment-${index + 1}`,
      text: comment,
      ...(context ? { context } : {}),
      ...(sourceUrl ? { source_url: sourceUrl } : {}),
    })),
  };
  setLoading(true);
  try {
    const response = await fetch("/v1/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ? JSON.stringify(body.detail) : `请求失败：${response.status}`);
    }
    renderResult(await response.json());
  } catch (error) {
    loadingState.hidden = true;
    emptyState.hidden = false;
    showError(error.message || "研判请求失败。");
  } finally {
    runButton.disabled = false;
    runButton.querySelector("span:last-child").textContent = "运行研判";
  }
});

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));
commentsInput.addEventListener("input", updateCount);
loadDemoButton.addEventListener("click", setDemo);
document.querySelector("#copy-json").addEventListener("click", async () => {
  if (!latestResult) return;
  await navigator.clipboard.writeText(JSON.stringify(latestResult, null, 2));
  document.querySelector("#copy-json").textContent = "已复制";
  setTimeout(() => { document.querySelector("#copy-json").textContent = "复制 JSON"; }, 1200);
});

fetch("/health").then((response) => {
  if (!response.ok) throw new Error();
  const state = document.querySelector("#service-state");
  state.classList.add("online");
  state.querySelector("span:last-child").textContent = "服务在线";
}).catch(() => {
  const state = document.querySelector("#service-state");
  state.classList.add("offline");
  state.querySelector("span:last-child").textContent = "服务离线";
});

setDemo();
