(function () {
  var badges = [{ selector: ".brand span", text: "MemoryEndpoints.com" }];
  for (var i = 0; i < badges.length; i += 1) {
    var node = document.querySelector(badges[i].selector);
    if (node && node.textContent !== badges[i].text) {
      node.textContent = badges[i].text;
    }
  }

  var consoleRoot = document.querySelector("[data-matm-console]");
  if (!consoleRoot) {
    return;
  }

  var state = {
    key: "",
    workspaceId: "",
    companyId: "",
    projectId: "",
    agentId: "human-verifier-agent",
    firstNotificationId: "",
    firstReviewId: "",
  };

  function pick(selector) {
    return consoleRoot.querySelector(selector);
  }

  function pretty(value) {
    return JSON.stringify(value, null, 2);
  }

  function setStatus(text, isError) {
    var node = pick("[data-console-status]");
    if (node) {
      node.textContent = text;
      node.className = isError ? "console-status error" : "console-status";
    }
  }

  function render(selector, value) {
    var node = pick(selector);
    if (node) {
      node.textContent = pretty(value);
    }
  }

  function clear(node) {
    while (node && node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  function shortId(value) {
    var text = String(value || "");
    if (!text) {
      return "not set";
    }
    var parts = text.split("-");
    if (parts.length > 1) {
      return parts[0] + "-" + parts.slice(1).join("").slice(0, 8);
    }
    return text.length > 12 ? text.slice(0, 12) : text;
  }

  function formatBytes(value) {
    var number = Number(value || 0);
    if (number >= 1024 * 1024) {
      return (number / (1024 * 1024)).toFixed(1) + " MB";
    }
    if (number >= 1024) {
      return (number / 1024).toFixed(1) + " KB";
    }
    return number + " B";
  }

  function appendBadge(parent, text, kind) {
    if (!text) {
      return;
    }
    parent.appendChild(el("span", "status-badge " + (kind || ""), text));
  }

  function appendMeta(parent, items) {
    var meta = el("div", "row-meta");
    (items || []).filter(Boolean).forEach(function (item) {
      meta.appendChild(el("span", "", item));
    });
    parent.appendChild(meta);
  }

  function copySafeText(value, label) {
    if (!value || !navigator.clipboard) {
      setStatus("Clipboard is unavailable for " + label + ".", true);
      return;
    }
    navigator.clipboard.writeText(value).then(function () {
      setStatus(label + " copied.", false);
    }).catch(function () {
      setStatus("Could not copy " + label + ".", true);
    });
  }

  function renderEmpty(selector, text) {
    var node = pick(selector);
    if (!node) {
      return;
    }
    clear(node);
    node.appendChild(el("p", "empty-state", text));
  }

  function summaryCard(title, value, meta, badges) {
    var card = el("article", "summary-card");
    card.appendChild(el("div", "summary-label", title));
    card.appendChild(el("strong", "", value || "Not available"));
    if (meta) {
      card.appendChild(el("span", "summary-meta", meta));
    }
    var badgeLine = el("div", "badge-line");
    (badges || []).forEach(function (badge) {
      appendBadge(badgeLine, badge.text, badge.kind);
    });
    if (badgeLine.childNodes.length) {
      card.appendChild(badgeLine);
    }
    return card;
  }

  function renderWorkspaceSummary(workspace) {
    var node = pick("[data-console-workspace-summary]");
    if (!node) {
      return;
    }
    clear(node);
    if (!workspace || !workspace.workspaceId) {
      node.appendChild(el("p", "empty-state", "Workspace details will appear after the key is accepted."));
      return;
    }
    var account = workspace.accounts && workspace.accounts.length ? workspace.accounts[0] : {};
    var company = workspace.company || {};
    var project = workspace.projects && workspace.projects.length ? workspace.projects[0] : {};
    node.appendChild(summaryCard("Account", account.label || workspace.accountId, shortId(account.accountId || workspace.accountId), [
      { text: account.role || "owner", kind: "neutral" },
      { text: account.status || "active", kind: "good" },
    ]));
    node.appendChild(summaryCard("Company", company.label || workspace.companyId, shortId(company.companyId || workspace.companyId), [
      { text: company.status || "active", kind: "good" },
    ]));
    node.appendChild(summaryCard("Workspace", workspace.label || workspace.workspaceId, shortId(workspace.workspaceId), [
      { text: workspace.plan || "plan unknown", kind: "neutral" },
      { text: workspace.status || "active", kind: "good" },
    ]));
    node.appendChild(summaryCard("Project", project.label || workspace.primaryProjectId, shortId(project.projectId || workspace.primaryProjectId), [
      { text: project.status || "active", kind: "good" },
    ]));
    node.appendChild(summaryCard(
      "Storage",
      formatBytes(workspace.storageUsedBytes) + " used",
      formatBytes(workspace.storageRemainingBytes) + " remaining",
      [{ text: workspace.quotaExceeded ? "quota exceeded" : "within quota", kind: workspace.quotaExceeded ? "warn" : "good" }]
    ));
    node.appendChild(summaryCard("Redaction", workspace.rawKeyStoredByServer ? "Check key handling" : "Key not stored raw", "Values are public-safe", [
      { text: workspace.rawKeyStoredByServer ? "review" : "pass", kind: workspace.rawKeyStoredByServer ? "warn" : "good" },
    ]));
  }

  function resultRow(title, summary, badges, metaItems) {
    var row = el("article", "result-row");
    var top = el("div", "result-row-top");
    top.appendChild(el("h3", "", title || "Untitled"));
    var badgeLine = el("div", "badge-line");
    (badges || []).forEach(function (badge) {
      appendBadge(badgeLine, badge.text, badge.kind);
    });
    top.appendChild(badgeLine);
    row.appendChild(top);
    if (summary) {
      row.appendChild(el("p", "result-summary", summary));
    }
    appendMeta(row, metaItems);
    return row;
  }

  function renderMemorySummary(payload) {
    var node = pick("[data-console-memory-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No hosted memory matched this search."));
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " hosted memory item(s). Filesystem docs are excluded from protected search."));
    items.forEach(function (item) {
      node.appendChild(resultRow(
        item.title || item.subject,
        item.summary,
        [
          { text: item.scope, kind: "neutral" },
          { text: item.memoryType, kind: "neutral" },
          { text: item.reviewStatus || item.promotionState, kind: item.reviewStatus === "quarantined" ? "warn" : "good" },
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
        ],
        [
          "actor " + (item.actorAgentId || "unknown"),
          "id " + shortId(item.eventId),
          item.createdAt || "",
          "source " + (item.source || "api"),
        ]
      ));
    });
  }

  function renderInboxSummary(payload) {
    var node = pick("[data-console-inbox-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No unread messages for this agent."));
      return;
    }
    node.appendChild(el("div", "result-count", (payload.unreadCount || items.length) + " unread message(s)."));
    items.forEach(function (item) {
      var message = item.message || {};
      var notification = item.notification || {};
      var target = message.targetAgentId || notification.targetAgentId;
      node.appendChild(resultRow(
        target ? "Targeted message" : "Broadcast message",
        message.safeSummary,
        [
          { text: target ? "targeted" : "broadcast", kind: target ? "neutral" : "good" },
          { text: notification.status || "unread", kind: notification.status === "read" ? "good" : "warn" },
          { text: message.responseRequired ? "response required" : "ack only", kind: message.responseRequired ? "warn" : "neutral" },
          { text: message.valuesRedacted ? "redacted" : "", kind: "good" },
        ],
        [
          "from " + (message.senderAgentId || "unknown"),
          "to " + (target || "all agents"),
          "message " + shortId(message.messageId),
          "notification " + shortId(notification.notificationId),
          message.createdAt || "",
        ]
      ));
    });
  }

  function renderReceiptSummary(payload) {
    var node = pick("[data-console-receipts-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No receipts for the current agent yet."));
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " receipt(s)."));
    items.forEach(function (item) {
      node.appendChild(resultRow(
        "Notification " + (item.status || "read"),
        "Receipt confirms an acknowledgement without exposing raw private payloads.",
        [
          { text: item.status || "read", kind: "good" },
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
          { text: item.rawPayloadExposed ? "raw payload exposed" : "raw payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
        ],
        [
          "consumer " + (item.consumerAgentId || "unknown"),
          "receipt " + shortId(item.receiptId),
          "notification " + shortId(item.notificationId),
          item.createdAt || "",
        ]
      ));
    });
  }

  function renderAuditSummary(payload) {
    var node = pick("[data-console-audit-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No audit events returned."));
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " audit event(s), newest first."));
    items.slice().reverse().slice(0, 24).forEach(function (item) {
      node.appendChild(resultRow(
        item.action,
        "Actor " + (item.actor || "unknown") + " touched " + (item.target || "unknown target") + ".",
        [
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
          { text: item.rawCredentialExposed ? "credential exposed" : "credentials hidden", kind: item.rawCredentialExposed ? "warn" : "good" },
          { text: item.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
        ],
        [
          "audit " + shortId(item.auditId),
          item.createdAt || "",
        ]
      ));
    });
  }

  function renderReviewSummary(payload) {
    var node = pick("[data-console-review-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No review queue items matched this status."));
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " review item(s)."));
    items.forEach(function (item) {
      var row = resultRow(
        "Review " + shortId(item.reviewId),
        item.publicSafeSummary || "No public-safe summary returned.",
        [
          { text: item.status || "pending", kind: item.status === "promoted" ? "good" : (item.status === "quarantined" ? "warn" : "neutral") },
          { text: item.firewallDecision || "review", kind: item.firewallDecision === "quarantine_for_review" ? "warn" : "good" },
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
        ],
        [
          "proposed by " + (item.proposedByAgentId || "unknown"),
          "review " + shortId(item.reviewId),
          "memory " + shortId(item.memoryEventId),
          "risk " + String(item.riskScore || 0),
          item.createdAt || "",
        ]
      );
      var actions = el("div", "row-actions");
      var useButton = el("button", "button compact", "Use review");
      var copyButton = el("button", "button compact", "Copy review id");
      useButton.type = "button";
      copyButton.type = "button";
      useButton.addEventListener("click", function () {
        var decisionForm = pick("[data-console-review-decision]");
        if (decisionForm) {
          decisionForm.elements.reviewId.value = item.reviewId || "";
          setStatus("Review selected. Choose a decision and submit.", false);
        }
      });
      copyButton.addEventListener("click", function () {
        copySafeText(item.reviewId, "Review id");
      });
      actions.appendChild(useButton);
      actions.appendChild(copyButton);
      row.appendChild(actions);
      node.appendChild(row);
    });
  }

  function authHeaders(extra) {
    var headers = {
      "Accept": "application/json",
      "Authorization": "Bearer " + state.key,
    };
    if (extra) {
      Object.keys(extra).forEach(function (key) {
        headers[key] = extra[key];
      });
    }
    return headers;
  }

  function api(path, options) {
    options = options || {};
    var fetchOptions = {
      method: options.method || "GET",
      headers: authHeaders(options.headers),
      cache: "no-store",
    };
    if (options.body) {
      fetchOptions.headers["Content-Type"] = "application/json";
      fetchOptions.body = JSON.stringify(options.body);
    }
    return fetch(path, fetchOptions).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || payload.ok === false) {
          var detail = payload.error && payload.error.detail ? payload.error.detail : "Request failed.";
          throw new Error(detail);
        }
        return payload;
      });
    });
  }

  function query(params) {
    var parts = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value !== undefined && value !== null && value !== "") {
        parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
      }
    });
    return parts.join("&");
  }

  function loadWorkspace() {
    return api("/api/matm/workspace").then(function (payload) {
      var workspace = payload.workspace || {};
      state.workspaceId = workspace.workspaceId || state.workspaceId;
      state.companyId = workspace.companyId || state.companyId;
      state.projectId = workspace.primaryProjectId || state.projectId;
      render("[data-console-workspace]", workspace);
      renderWorkspaceSummary(workspace);
      setStatus("Workspace loaded. Key remains session-local.", false);
      return workspace;
    });
  }

  function registerAgent(agentId) {
    if (!agentId) {
      return Promise.resolve();
    }
    return api("/api/matm/agents/register", {
      method: "POST",
      headers: {"Idempotency-Key": "console-register-" + agentId},
      body: {
        workspaceId: state.workspaceId,
        agentId: agentId,
        displayName: agentId,
      },
    });
  }

  function refreshMemory(searchTerm) {
    var qs = query({workspace_id: state.workspaceId, q: searchTerm || ""});
    return api("/api/matm/search?" + qs).then(function (payload) {
      render("[data-console-memory-output]", payload);
      renderMemorySummary(payload);
      return payload;
    });
  }

  function refreshInbox(agentId) {
    var qs = query({workspace_id: state.workspaceId, agent_id: agentId || state.agentId});
    return api("/api/matm/current-message?" + qs).then(function (payload) {
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstNotificationId = first && first.notification ? first.notification.notificationId : "";
      render("[data-console-inbox-output]", payload);
      renderInboxSummary(payload);
      return payload;
    });
  }

  function refreshReceipts() {
    var qs = query({workspace_id: state.workspaceId, consumer_agent_id: state.agentId});
    return api("/api/matm/receipts?" + qs).then(function (payload) {
      render("[data-console-receipts-output]", payload);
      renderReceiptSummary(payload);
      return payload;
    });
  }

  function refreshAudit() {
    var qs = query({workspace_id: state.workspaceId, limit: "50"});
    return api("/api/matm/audit-log?" + qs).then(function (payload) {
      render("[data-console-audit-output]", payload);
      renderAuditSummary(payload);
      return payload;
    });
  }

  function refreshReviewQueue(status) {
    var qs = query({workspace_id: state.workspaceId, status: status || ""});
    return api("/api/matm/review-queue?" + qs).then(function (payload) {
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstReviewId = first ? first.reviewId : "";
      render("[data-console-review-output]", payload);
      renderReviewSummary(payload);
      var decisionForm = pick("[data-console-review-decision]");
      if (decisionForm && state.firstReviewId && !decisionForm.elements.reviewId.value) {
        decisionForm.elements.reviewId.value = state.firstReviewId;
      }
      return payload;
    });
  }

  var authForm = pick("[data-console-auth]");
  if (authForm) {
    authForm.addEventListener("submit", function (event) {
      event.preventDefault();
      state.key = authForm.elements.workspaceKey.value.trim();
      state.agentId = authForm.elements.agentId.value.trim() || "human-verifier-agent";
      if (!state.key) {
        setStatus("Workspace key is required.", true);
        return;
      }
      loadWorkspace()
        .then(function () { return registerAgent(state.agentId); })
        .then(function () { return refreshMemory("verification"); })
        .then(function () { return refreshReviewQueue("pending"); })
        .then(function () { return refreshInbox(state.agentId); })
        .then(refreshReceipts)
        .then(refreshAudit)
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var memoryForm = pick("[data-console-memory]");
  if (memoryForm) {
    memoryForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var tags = memoryForm.elements.tags.value.split(",").map(function (item) {
        return item.trim();
      }).filter(Boolean);
      api("/api/matm/memory-events/submit", {
        method: "POST",
        headers: {"Idempotency-Key": "console-memory-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          actorAgentId: memoryForm.elements.actorAgentId.value.trim(),
          scope: memoryForm.elements.scope.value,
          scopeId: memoryForm.elements.scope.value === "company" ? state.companyId : (memoryForm.elements.scope.value === "project" ? state.projectId : state.workspaceId),
          title: memoryForm.elements.title.value.trim(),
          summary: memoryForm.elements.summary.value.trim(),
          tags: tags,
          memoryType: "status",
          source: "MemoryEndpoints.com human verification console",
        },
      })
        .then(function () { return refreshMemory("verification"); })
        .then(function () { return refreshReviewQueue(reviewForm ? reviewForm.elements.status.value : "pending"); })
        .then(function () { setStatus("Memory saved; search and review queue refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var searchForm = pick("[data-console-search]");
  if (searchForm) {
    searchForm.addEventListener("submit", function (event) {
      event.preventDefault();
      refreshMemory(searchForm.elements.query.value).catch(function (error) {
        setStatus(error.message, true);
      });
    });
  }

  var messageForm = pick("[data-console-message]");
  if (messageForm) {
    messageForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var target = messageForm.elements.targetAgentId.value.trim();
      var body = {
        workspaceId: state.workspaceId,
        senderAgentId: messageForm.elements.senderAgentId.value.trim(),
        safeSummary: messageForm.elements.safeSummary.value.trim(),
        responseRequired: messageForm.elements.responseRequired.checked,
      };
      if (target) {
        body.targetAgentId = target;
      }
      api("/api/matm/agent-messages", {
        method: "POST",
        headers: {"Idempotency-Key": "console-message-" + Date.now()},
        body: body,
      })
        .then(function () { return refreshInbox(state.agentId); })
        .then(function () { setStatus(target ? "Targeted message sent." : "Broadcast message sent.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var reviewForm = pick("[data-console-review]");
  if (reviewForm) {
    reviewForm.addEventListener("submit", function (event) {
      event.preventDefault();
      refreshReviewQueue(reviewForm.elements.status.value).catch(function (error) {
        setStatus(error.message, true);
      });
    });
  }

  var reviewDecisionForm = pick("[data-console-review-decision]");
  if (reviewDecisionForm) {
    reviewDecisionForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var reviewId = reviewDecisionForm.elements.reviewId.value.trim() || state.firstReviewId;
      var decision = reviewDecisionForm.elements.decision.value;
      if (!reviewId) {
        setStatus("Review id is required.", true);
        return;
      }
      api("/api/matm/review-queue/decide", {
        method: "POST",
        headers: {"Idempotency-Key": "console-review-" + reviewId + "-" + decision + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          reviewId: reviewId,
          reviewerAgentId: reviewDecisionForm.elements.reviewerAgentId.value.trim(),
          decision: decision,
          reviewNote: reviewDecisionForm.elements.reviewNote.value.trim(),
        },
      })
        .then(function (payload) {
          render("[data-console-review-decision-output]", payload);
          return refreshReviewQueue(reviewForm ? reviewForm.elements.status.value : "pending");
        })
        .then(function () { return refreshMemory(searchForm ? searchForm.elements.query.value : ""); })
        .then(function () { setStatus("Review decision recorded and queue refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var inboxForm = pick("[data-console-inbox]");
  if (inboxForm) {
    inboxForm.addEventListener("submit", function (event) {
      event.preventDefault();
      state.agentId = inboxForm.elements.agentId.value.trim() || state.agentId;
      refreshInbox(state.agentId).catch(function (error) { setStatus(error.message, true); });
    });
  }

  var ackButton = pick("[data-console-ack]");
  if (ackButton) {
    ackButton.addEventListener("click", function () {
      if (!state.firstNotificationId) {
        setStatus("No unread notification is selected.", true);
        return;
      }
      api("/api/matm/notifications/ack", {
        method: "POST",
        headers: {"Idempotency-Key": "console-ack-" + state.firstNotificationId},
        body: {
          workspaceId: state.workspaceId,
          notificationId: state.firstNotificationId,
          consumerAgentId: state.agentId,
          status: "read",
        },
      })
        .then(function () { return refreshInbox(state.agentId); })
        .then(refreshReceipts)
        .then(function () { setStatus("Notification acknowledged and receipt refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var receiptsButton = pick("[data-console-receipts]");
  if (receiptsButton) {
    receiptsButton.addEventListener("click", function () {
      refreshReceipts().catch(function (error) { setStatus(error.message, true); });
    });
  }

  var auditButton = pick("[data-console-audit]");
  if (auditButton) {
    auditButton.addEventListener("click", function () {
      refreshAudit().catch(function (error) { setStatus(error.message, true); });
    });
  }
})();
