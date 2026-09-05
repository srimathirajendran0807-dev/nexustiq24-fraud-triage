const customerButtons = document.querySelectorAll(".customer-item");
const emptyState = document.getElementById("empty-state");
const loading = document.getElementById("loading");
const report = document.getElementById("report");
const errorState = document.getElementById("error-state");
const errorMessage = document.getElementById("error-message");

function showOnly(el) {
  [emptyState, loading, report, errorState].forEach((e) => e.classList.add("hidden"));
  el.classList.remove("hidden");
}

customerButtons.forEach((btn) => {
  btn.addEventListener("click", async () => {
    customerButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const customerId = btn.dataset.customerId;
    showOnly(loading);

    try {
      const res = await fetch("/api/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_id: customerId }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${res.status})`);
      }

      const data = await res.json();
      renderReport(data);
      showOnly(report);
    } catch (e) {
      errorMessage.textContent = e.message || "Something went wrong reaching the investigation service.";
      showOnly(errorState);
    }
  });
});

function renderReport(data) {
  document.getElementById("report-customer-id").textContent = data.customer_id;
  document.getElementById("report-customer-name").textContent = data.customer_name;

  const badge = document.getElementById("priority-badge");
  badge.textContent = data.priority;
  badge.className = "priority-badge " + data.priority;

  document.getElementById("overall-assessment").textContent = data.overall_assessment;

  const metaBits = [
    `${data.transactions_reviewed} transactions reviewed`,
    `${data.findings.length} finding(s)`,
    data.llm_narrative_available ? "narrative: Gemini-assisted" : "narrative: rules-only (LLM unavailable)",
  ];
  document.getElementById("report-meta").textContent = metaBits.join("  ·  ");

  const list = document.getElementById("findings-list");
  list.innerHTML = "";

  if (data.findings.length === 0) {
    const p = document.createElement("p");
    p.style.color = "var(--ink-soft)";
    p.style.fontSize = "14px";
    p.textContent = "No findings to display for this customer.";
    list.appendChild(p);
    return;
  }

  data.findings.forEach((f) => {
    const card = document.createElement("div");
    card.className = "finding-card";

    const head = document.createElement("div");
    head.className = "finding-head";
    head.innerHTML = `
      <span class="finding-rule-name">${escapeHtml(f.rule_name)}</span>
      <span class="finding-rule-id">${escapeHtml(f.rule_id)}</span>
    `;
    card.appendChild(head);

    const explanation = document.createElement("p");
    explanation.className = "finding-explanation";
    explanation.textContent = f.explanation || "Automated explanation unavailable — see raw evidence below.";
    card.appendChild(explanation);

    const txns = document.createElement("p");
    txns.className = "finding-txns";
    txns.textContent = "Transactions: " + f.txn_ids.join(", ");
    card.appendChild(txns);

    if (f.what_to_check_first) {
      const next = document.createElement("p");
      next.className = "finding-next";
      next.innerHTML = `<strong>Check first:</strong> ${escapeHtml(f.what_to_check_first)}`;
      card.appendChild(next);
    }

    const evidence = document.createElement("div");
    evidence.className = "finding-evidence";
    evidence.textContent = JSON.stringify(f.evidence, null, 2);
    card.appendChild(evidence);

    list.appendChild(card);
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}