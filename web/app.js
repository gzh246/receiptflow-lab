const statusLabels = {
  auto_match: "Auto matched",
  manual_review_ambiguous: "Review: ambiguous",
  manual_review_no_match: "Review: no match",
  manual_review_low_confidence: "Review: low confidence",
};

const state = {
  data: null,
  selectedId: null,
};

const byId = (id) => document.getElementById(id);

function statusClass(status) {
  if (status === "auto_match") return "success";
  if (typeof status === "string" && status.startsWith("manual_review_")) return "review";
  return "neutral";
}

function statusLabel(status) {
  return statusLabels[status] ?? "Unknown decision";
}

function appendTextCell(row, text, emphasize = false) {
  const cell = document.createElement("td");
  const content = emphasize ? document.createElement("strong") : cell;
  content.textContent = text;
  if (emphasize) cell.appendChild(content);
  row.appendChild(cell);
}

function formatCurrency(amount, currency) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(Number(amount));
}

function renderSummary(data) {
  byId("metric-total").textContent = data.summary.receipts;
  byId("metric-auto").textContent = data.summary.auto_matched;
  byId("metric-review").textContent = data.summary.manual_review;
  const policy = data.decision_policy;
  byId("policy-text").textContent =
    `Amount +/-${policy.amount_tolerance} | Date +/-${policy.date_window_days} days | ` +
    `Threshold ${policy.auto_match_threshold} | Ambiguity margin ${policy.ambiguity_margin}`;
}

function renderRows(data) {
  const tbody = byId("receipt-rows");
  tbody.replaceChildren();
  data.decisions.forEach((decision) => {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.dataset.receiptId = decision.receipt_id;
    if (decision.receipt_id === state.selectedId) tr.classList.add("selected");

    const receipt = decision.receipt;
    appendTextCell(tr, receipt.receipt_id, true);
    appendTextCell(tr, receipt.client_alias);
    appendTextCell(tr, formatCurrency(receipt.amount, receipt.currency));
    appendTextCell(tr, receipt.expense_date);

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `status-pill ${statusClass(decision.status)}`;
    status.textContent = statusLabel(decision.status);
    statusCell.appendChild(status);
    tr.appendChild(statusCell);

    const select = () => selectDecision(decision.receipt_id);
    tr.addEventListener("click", select);
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    tbody.appendChild(tr);
  });
}

function renderCandidates(decision) {
  const container = byId("candidate-list");
  container.replaceChildren();
  if (!decision.candidates.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No eligible candidates remained after the deterministic gates.";
    container.appendChild(empty);
    return;
  }

  decision.candidates.forEach((candidate) => {
    const row = document.createElement("div");
    row.className = "candidate-row";

    const expenseId = document.createElement("strong");
    expenseId.textContent = candidate.expense_id;

    const scoreDetails = document.createElement("div");
    const scoreTrack = document.createElement("div");
    scoreTrack.className = "score-track";
    const scoreFill = document.createElement("div");
    scoreFill.className = "score-fill";
    const safeScore = Math.max(0, Math.min(1, Number(candidate.score) || 0));
    scoreFill.style.width = `${safeScore * 100}%`;
    scoreTrack.appendChild(scoreFill);

    const metadata = document.createElement("span");
    metadata.className = "candidate-meta";
    metadata.textContent = `${candidate.days_apart} day(s) | ${candidate.client_state}`;
    scoreDetails.append(scoreTrack, metadata);

    const score = document.createElement("strong");
    score.textContent = safeScore.toFixed(3);
    row.append(expenseId, scoreDetails, score);
    container.appendChild(row);
  });
}

function selectDecision(receiptId) {
  state.selectedId = receiptId;
  const decision = state.data.decisions.find((item) => item.receipt_id === receiptId);
  if (!decision) return;

  renderRows(state.data);
  const receipt = decision.receipt;
  byId("detail-title").textContent = `${receipt.receipt_id} | ${receipt.client_alias}`;
  const status = byId("detail-status");
  status.textContent = statusLabel(decision.status);
  status.className = `status-pill ${statusClass(decision.status)}`;
  byId("detail-amount").textContent = formatCurrency(receipt.amount, receipt.currency);
  byId("detail-date").textContent = receipt.expense_date;
  byId("detail-client").textContent = `${receipt.client_alias} -> ${receipt.freshbooks_client_id}`;
  byId("detail-confidence").textContent = decision.confidence
    ? decision.confidence.toFixed(3)
    : "No candidate";
  byId("dropbox-path").textContent = decision.dropbox_folder;
  byId("idempotency-key").textContent = decision.idempotency_key;

  renderCandidates(decision);
  const reasons = byId("reason-list");
  reasons.replaceChildren();
  decision.reasons.forEach((reason) => {
    const li = document.createElement("li");
    li.textContent = reason;
    reasons.appendChild(li);
  });
}

async function loadData() {
  const response = await fetch("../demo_output.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load demo output: ${response.status}`);
  state.data = await response.json();
  state.selectedId = state.data.decisions[0]?.receipt_id ?? null;
  renderSummary(state.data);
  renderRows(state.data);
  if (state.selectedId) selectDecision(state.selectedId);
}

async function runSimulation() {
  const button = byId("run-button");
  document.body.classList.add("is-running");
  button.disabled = true;
  button.querySelector("span").textContent = "Evaluating gates...";
  await new Promise((resolve) => setTimeout(resolve, 700));
  renderSummary(state.data);
  renderRows(state.data);
  selectDecision(state.selectedId || state.data.decisions[0].receipt_id);
  document.body.classList.remove("is-running");
  button.disabled = false;
  button.querySelector("span").textContent = "Run simulation";
}

byId("run-button").addEventListener("click", runSimulation);

loadData()
  .then(() => window.lucide?.createIcons())
  .catch((error) => {
    byId("policy-text").textContent = error.message;
    console.error(error);
  });
