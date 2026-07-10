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
    workspace: null,
    agentId: "human-verifier-agent",
    firstNotificationId: "",
    visibleNotificationIds: [],
    firstReviewId: "",
  };
  var agentLanes = [
    { agentId: "human-verifier-agent", label: "Human" },
    { agentId: "codex-agent", label: "Codex" },
    { agentId: "swarm-observer-agent", label: "Observer" },
  ];

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

  function appendFilterSummary(parent, filters) {
    var active = filters || {};
    var keys = Object.keys(active).filter(function (key) {
      return active[key] !== undefined && active[key] !== null && active[key] !== "";
    });
    if (!keys.length) {
      return;
    }
    var summary = el("div", "filter-summary");
    summary.appendChild(el("span", "filter-summary-label", "Filters"));
    keys.forEach(function (key) {
      summary.appendChild(el("span", "status-badge neutral", key + ": " + active[key]));
    });
    parent.appendChild(summary);
  }

  function memoryScopeGroups(items) {
    var order = ["account", "company", "workspace", "project"];
    var groups = {};
    (items || []).forEach(function (item) {
      var scope = item.scope || "other";
      if (!groups[scope]) {
        groups[scope] = [];
      }
      groups[scope].push(item);
    });
    Object.keys(groups).forEach(function (scope) {
      if (order.indexOf(scope) === -1) {
        order.push(scope);
      }
    });
    return order.filter(function (scope) {
      return groups[scope] && groups[scope].length;
    }).map(function (scope) {
      return { scope: scope, items: groups[scope] };
    });
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

  function sessionItem(title, value, meta, badges) {
    var item = el("article", "session-item");
    item.appendChild(el("span", "summary-label", title));
    item.appendChild(el("strong", "", value || "Not available"));
    if (meta) {
      item.appendChild(el("span", "summary-meta", meta));
    }
    var badgeLine = el("div", "badge-line");
    (badges || []).forEach(function (badge) {
      appendBadge(badgeLine, badge.text, badge.kind);
    });
    if (badgeLine.childNodes.length) {
      item.appendChild(badgeLine);
    }
    return item;
  }

  function renderSessionSummary(workspace) {
    var node = pick("[data-console-session-summary]");
    if (!node) {
      return;
    }
    clear(node);
    if (!workspace || !workspace.workspaceId) {
      node.appendChild(el("p", "empty-state", "Session status will appear after the workspace loads."));
      return;
    }
    var hostname = window.location.hostname || "";
    var isLocal = hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
    var account = workspace.accounts && workspace.accounts.length ? workspace.accounts[0] : {};
    var company = workspace.company || {};
    var project = workspace.projects && workspace.projects.length ? workspace.projects[0] : {};
    var hierarchyReady = Boolean(
      (account.accountId || workspace.accountId) &&
      (company.companyId || workspace.companyId) &&
      workspace.workspaceId &&
      (project.projectId || workspace.primaryProjectId)
    );
    node.appendChild(sessionItem("Surface", isLocal ? "local site" : "live site", window.location.origin || hostname, [
      { text: isLocal ? "local" : "production", kind: isLocal ? "neutral" : "good" },
    ]));
    node.appendChild(sessionItem("Boundary", hierarchyReady ? "4 levels loaded" : "check boundary", "account -> company -> workspace -> project", [
      { text: hierarchyReady ? "pass" : "review", kind: hierarchyReady ? "good" : "warn" },
    ]));
    node.appendChild(sessionItem("Key", workspace.rawKeyStoredByServer ? "review key handling" : "not echoed", "browser session only", [
      { text: workspace.rawKeyStoredByServer ? "review" : "private", kind: workspace.rawKeyStoredByServer ? "warn" : "good" },
    ]));
    node.appendChild(sessionItem("Agent", state.agentId, "current inbox lane", [
      { text: "active", kind: "good" },
    ]));
    var actions = el("nav", "session-actions");
    actions.setAttribute("aria-label", "Loaded workspace shortcuts");
    [
      { href: "#memory-workflow", label: "Memory" },
      { href: "#message-lanes", label: "Messages" },
      { href: "#receipts-audit", label: "Receipts" },
    ].forEach(function (item) {
      var link = el("a", "button compact", item.label);
      link.href = item.href;
      actions.appendChild(link);
    });
    node.appendChild(actions);
  }

  function boundaryStep(label, value, status, copyLabel) {
    var step = el("div", "boundary-step");
    step.appendChild(el("span", "boundary-label", label));
    step.appendChild(el("strong", "", value || "Not available"));
    step.appendChild(el("span", "summary-meta", shortId(value)));
    var footer = el("div", "boundary-step-footer");
    appendBadge(footer, status || "active", status === "active" ? "good" : "neutral");
    if (value) {
      var button = el("button", "button compact", "Copy ID");
      button.type = "button";
      button.setAttribute("data-console-copy-action", "");
      button.setAttribute("aria-label", copyLabel || (label + " id"));
      button.addEventListener("click", function () {
        copySafeText(value, copyLabel || (label + " id"));
      });
      footer.appendChild(button);
    }
    step.appendChild(footer);
    return step;
  }

  function renderWorkspaceBoundaryChain(workspace, account, company, project) {
    var chain = el("div", "boundary-chain");
    chain.appendChild(el("div", "result-count", "Boundary chain: account -> company -> workspace -> project"));
    var steps = el("div", "boundary-steps");
    [
      {
        label: "Account",
        value: account.accountId || workspace.accountId,
        status: account.status || "active",
        copyLabel: "Account id",
      },
      {
        label: "Company",
        value: company.companyId || workspace.companyId,
        status: company.status || "active",
        copyLabel: "Company id",
      },
      {
        label: "Workspace",
        value: workspace.workspaceId,
        status: workspace.status || "active",
        copyLabel: "Workspace id",
      },
      {
        label: "Project",
        value: project.projectId || workspace.primaryProjectId,
        status: project.status || "active",
        copyLabel: "Project id",
      },
    ].forEach(function (item) {
      steps.appendChild(boundaryStep(item.label, item.value, item.status, item.copyLabel));
    });
    chain.appendChild(steps);
    return chain;
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
    node.appendChild(renderWorkspaceBoundaryChain(workspace, account, company, project));
    appendCopyActions(node.appendChild(summaryCard("Account", account.label || workspace.accountId, shortId(account.accountId || workspace.accountId), [
      { text: account.role || "owner", kind: "neutral" },
      { text: account.status || "active", kind: "good" },
    ])), [
      { label: "Copy account id", copyLabel: "Account id", value: account.accountId || workspace.accountId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Company", company.label || workspace.companyId, shortId(company.companyId || workspace.companyId), [
      { text: company.status || "active", kind: "good" },
    ])), [
      { label: "Copy company id", copyLabel: "Company id", value: company.companyId || workspace.companyId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Workspace", workspace.label || workspace.workspaceId, shortId(workspace.workspaceId), [
      { text: workspace.plan || "plan unknown", kind: "neutral" },
      { text: workspace.status || "active", kind: "good" },
    ])), [
      { label: "Copy workspace id", copyLabel: "Workspace id", value: workspace.workspaceId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Project", project.label || workspace.primaryProjectId, shortId(project.projectId || workspace.primaryProjectId), [
      { text: project.status || "active", kind: "good" },
    ])), [
      { label: "Copy project id", copyLabel: "Project id", value: project.projectId || workspace.primaryProjectId },
    ]);
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

  function appendCopyActions(row, actions) {
    var usable = (actions || []).filter(function (action) {
      return action && action.value;
    });
    if (!usable.length) {
      return row;
    }
    var wrapper = el("div", "row-actions");
    usable.forEach(function (action) {
      var button = el("button", "button compact", action.label);
      button.type = "button";
      button.setAttribute("data-console-copy-action", "");
      button.setAttribute("aria-label", action.copyLabel || action.label);
      button.addEventListener("click", function () {
        copySafeText(action.value, action.copyLabel || action.label);
      });
      wrapper.appendChild(button);
    });
    row.appendChild(wrapper);
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
      appendFilterSummary(node, payload && payload.filters);
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " hosted memory item(s). Filesystem docs are excluded from protected search."));
    appendFilterSummary(node, payload && payload.filters);
    memoryScopeGroups(items).forEach(function (group) {
      node.appendChild(el("div", "result-group-title", group.scope + " memory (" + group.items.length + ")"));
      group.items.forEach(function (item) {
        var row = resultRow(
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
        );
        appendCopyActions(row, [
          { label: "Copy memory id", copyLabel: "Memory id", value: item.eventId },
        ]);
        node.appendChild(row);
      });
    });
  }

  function renderMemorySubmissionSummary(payload) {
    var node = pick("[data-console-memory-submit-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var event = (payload && payload.event) || {};
    var submission = (payload && payload.submission) || {};
    var memoryId = submission.memoryEventId || event.eventId || "";
    if (!memoryId) {
      node.appendChild(el("p", "empty-state", "Saved memory confirmations will appear here."));
      return;
    }
    var firewall = event.firewall || {};
    var firewallDecision = submission.firewallDecision || firewall.decision || "accepted";
    var row = resultRow(
      "Memory saved",
      event.summary || "Memory event recorded without exposing raw private payloads.",
      [
        { text: submission.scope || event.scope || "workspace", kind: "neutral" },
        { text: submission.memoryType || event.memoryType || "memory", kind: "neutral" },
        { text: submission.reviewStatus || event.reviewStatus || "pending", kind: (submission.reviewStatus || event.reviewStatus) === "quarantined" ? "warn" : "good" },
        { text: firewallDecision, kind: firewallDecision === "quarantine_for_review" ? "warn" : "good" },
        { text: submission.valuesRedacted ? "redacted" : "", kind: "good" },
        { text: submission.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: submission.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "memory " + shortId(memoryId),
        "review " + shortId(submission.reviewId || event.reviewId),
        "actor " + (event.actorAgentId || "unknown"),
        event.createdAt || "",
      ]
    );
    row.className += " submission-row";
    appendCopyActions(row, [
      { label: "Copy memory id", copyLabel: "Memory id", value: memoryId },
      { label: "Copy review id", copyLabel: "Review id", value: submission.reviewId || event.reviewId },
    ]);
    node.appendChild(row);
  }

  function renderInboxSummary(payload, agentId) {
    var node = pick("[data-console-inbox-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    var lane = agentId || state.agentId || "selected agent";
    appendFilterSummary(node, payload && payload.filters);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No unread messages for " + lane + "."));
      return;
    }
    var deliveryCounts = (payload && payload.deliveryCounts) || {};
    var countText = (payload.unreadCount || items.length) + " unread message(s) for " + lane + ".";
    if (deliveryCounts.broadcast !== undefined || deliveryCounts.targeted !== undefined) {
      countText += " " + (deliveryCounts.broadcast || 0) + " broadcast, " + (deliveryCounts.targeted || 0) + " targeted.";
    }
    node.appendChild(el("div", "result-count", countText));
    items.forEach(function (item) {
      var message = item.message || {};
      var notification = item.notification || {};
      var delivery = item.delivery || {};
      var target = delivery.targetAgentId || message.targetAgentId || notification.targetAgentId;
      var messageType = delivery.messageType || (target ? "targeted" : "broadcast");
      var isTargeted = messageType === "targeted";
      var row = resultRow(
        isTargeted ? "Targeted message" : "Broadcast message",
        message.safeSummary,
        [
          { text: messageType, kind: isTargeted ? "neutral" : "good" },
          { text: notification.status || "unread", kind: notification.status === "read" ? "good" : "warn" },
          { text: message.responseRequired ? "response required" : "ack only", kind: message.responseRequired ? "warn" : "neutral" },
          { text: message.valuesRedacted ? "redacted" : "", kind: "good" },
        ],
        [
          "from " + (message.senderAgentId || "unknown"),
          "to " + (target || "all agents"),
          "delivery " + messageType,
          "response " + (delivery.responseDisposition || notification.responseDisposition || "viewed_acknowledgement"),
          "message " + shortId(message.messageId),
          "notification " + shortId(notification.notificationId),
          message.createdAt || "",
        ]
      );
      appendCopyActions(row, [
        { label: "Copy message id", copyLabel: "Message id", value: message.messageId },
        { label: "Copy notification id", copyLabel: "Notification id", value: notification.notificationId },
      ]);
      node.appendChild(row);
    });
  }

  function renderMessageDelivery(payload, refreshedAgentId) {
    var node = pick("[data-console-message-delivery]");
    if (!node) {
      return;
    }
    clear(node);
    var message = (payload && payload.message) || {};
    var notification = (payload && payload.notification) || {};
    var delivery = (payload && payload.delivery) || {};
    var target = delivery.targetAgentId || message.targetAgentId || notification.targetAgentId || "";
    var messageType = delivery.messageType || (target ? "targeted" : "broadcast");
    var isTargeted = messageType === "targeted";
    var refreshedLane = refreshedAgentId || target || state.agentId;
    var row = resultRow(
      isTargeted ? "Targeted message delivered" : "Broadcast delivered",
      message.safeSummary || "The message was accepted by the current-message lane.",
      [
        { text: messageType, kind: isTargeted ? "neutral" : "good" },
        { text: message.responseRequired ? "response required" : "ack only", kind: message.responseRequired ? "warn" : "neutral" },
        { text: message.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "from " + (message.senderAgentId || "unknown"),
        "to " + (target || "all agents"),
        "delivery " + messageType,
        "response " + (delivery.responseDisposition || notification.responseDisposition || "viewed_acknowledgement"),
        "message " + shortId(message.messageId),
        "notification " + shortId(notification.notificationId),
        "refreshed " + refreshedLane + " inbox",
      ]
    );
    row.className += " delivery-row";
    appendCopyActions(row, [
      { label: "Copy message id", copyLabel: "Message id", value: message.messageId },
      { label: "Copy notification id", copyLabel: "Notification id", value: notification.notificationId },
    ]);
    node.appendChild(el("div", "result-count", target ? refreshedLane + " inbox refreshed." : "Broadcast accepted; current inbox refreshed."));
    node.appendChild(row);
  }

  function renderLaneOverview(results) {
    var node = pick("[data-console-lane-overview]");
    if (!node) {
      return;
    }
    clear(node);
    if (!results || !results.length) {
      node.appendChild(el("p", "empty-state", "All-lane unread counts will appear after the workspace loads."));
      return;
    }
    node.appendChild(el("div", "result-count", results.length + " agent lane(s) checked."));
    results.forEach(function (result) {
      var payload = result.payload || {};
      var items = payload.items || [];
      var unreadCount = payload.unreadCount !== undefined ? payload.unreadCount : items.length;
      var first = items.length ? items[0].message || {} : {};
      var row = resultRow(
        result.label + " inbox",
        result.ok
          ? (items.length ? first.safeSummary : "No unread current messages.")
          : (result.error || "Lane refresh failed."),
        [
          { text: result.ok ? "reachable" : "error", kind: result.ok ? "good" : "warn" },
          { text: unreadCount + " unread", kind: unreadCount ? "warn" : "good" },
        ],
        [
          "agent " + result.agentId,
          items.length ? "latest " + shortId(first.messageId) : "latest none",
        ]
      );
      var actions = el("div", "row-actions");
      var openButton = el("button", "button compact", "Open lane");
      openButton.type = "button";
      openButton.setAttribute("data-console-open-lane", result.agentId);
      openButton.addEventListener("click", function () {
        openInboxLane(result.agentId, result.label + " inbox").catch(function (error) {
          setStatus(error.message, true);
        });
      });
      actions.appendChild(openButton);
      row.appendChild(actions);
      node.appendChild(row);
    });
  }

  function renderReceiptSummary(payload) {
    var node = pick("[data-console-receipts-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    appendFilterSummary(node, payload && payload.filters);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No receipts for the current agent yet."));
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " receipt(s)."));
    items.forEach(function (item) {
      var row = resultRow(
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
      );
      appendCopyActions(row, [
        { label: "Copy receipt id", copyLabel: "Receipt id", value: item.receiptId },
        { label: "Copy notification id", copyLabel: "Notification id", value: item.notificationId },
      ]);
      node.appendChild(row);
    });
  }

  function renderAcknowledgementSummary(payload) {
    var node = pick("[data-console-ack-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var receipts = [];
    if (payload && payload.receipt) {
      receipts.push(payload.receipt);
    }
    if (payload && payload.receipts) {
      receipts = receipts.concat(payload.receipts);
    }
    if (!receipts.length) {
      node.appendChild(el("p", "empty-state", "Acknowledgement receipts will appear after messages are marked read."));
      return;
    }
    if (receipts.length > 1) {
      node.appendChild(el("div", "result-count", receipts.length + " acknowledgement receipt(s) recorded."));
    }
    receipts.forEach(function (receipt) {
      var row = resultRow(
        "Acknowledgement recorded",
        "Receipt confirms the message was marked read without exposing raw private payloads.",
        [
          { text: receipt.status || "read", kind: "good" },
          { text: receipt.valuesRedacted ? "redacted" : "", kind: "good" },
          { text: receipt.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: receipt.rawPayloadExposed ? "warn" : "good" },
        ],
        [
          "consumer " + (receipt.consumerAgentId || "unknown"),
          "receipt " + shortId(receipt.receiptId),
          "notification " + shortId(receipt.notificationId),
          receipt.createdAt || "",
        ]
      );
      appendCopyActions(row, [
        { label: "Copy receipt id", copyLabel: "Receipt id", value: receipt.receiptId },
        { label: "Copy notification id", copyLabel: "Notification id", value: receipt.notificationId },
      ]);
      node.appendChild(row);
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
      appendFilterSummary(node, payload && payload.filters);
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " audit event(s), newest first."));
    appendFilterSummary(node, payload && payload.filters);
    items.slice().reverse().slice(0, 24).forEach(function (item) {
      var detailSummary = item.detailsSummary || [];
      var metaItems = [
        "audit " + shortId(item.auditId),
        item.createdAt || "",
      ].concat(detailSummary);
      var row = resultRow(
        item.action,
        "Actor " + (item.actor || "unknown") + " touched " + (item.target || "unknown target") + ".",
        [
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
          { text: item.rawCredentialExposed ? "credential exposed" : "credentials hidden", kind: item.rawCredentialExposed ? "warn" : "good" },
          { text: item.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
        ],
        metaItems
      );
      appendCopyActions(row, [
        { label: "Copy audit id", copyLabel: "Audit id", value: item.auditId },
      ]);
      node.appendChild(row);
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

  function renderReviewDecisionSummary(payload) {
    var node = pick("[data-console-review-decision-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var review = (payload && payload.review) || {};
    if (!review.reviewId) {
      node.appendChild(el("p", "empty-state", "Review decisions will appear as operator confirmation rows."));
      return;
    }
    var status = review.status || "recorded";
    var row = resultRow(
      "Review decision " + status,
      "Decision recorded without exposing the raw review note.",
      [
        { text: status, kind: status === "promoted" ? "good" : (status === "quarantined" ? "warn" : "neutral") },
        { text: review.valuesRedacted ? "redacted" : "", kind: "good" },
        { text: review.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: review.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "review " + shortId(review.reviewId),
        "memory " + shortId(review.memoryEventId),
        "reviewer " + (review.reviewerAgentId || "unknown"),
        review.decidedAt || review.updatedAt || "",
      ]
    );
    appendCopyActions(row, [
      { label: "Copy review id", copyLabel: "Review id", value: review.reviewId },
      { label: "Copy memory id", copyLabel: "Memory id", value: review.memoryEventId },
    ]);
    node.appendChild(row);
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
      state.workspace = workspace;
      render("[data-console-workspace]", workspace);
      renderSessionSummary(workspace);
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

  function memorySearchFilters(searchTerm) {
    var filters = {workspace_id: state.workspaceId, q: searchTerm || ""};
    var form = pick("[data-console-search]");
    if (form) {
      filters.scope = form.elements.scope ? form.elements.scope.value : "";
      filters.memory_type = form.elements.memoryType ? form.elements.memoryType.value : "";
      filters.review_status = form.elements.reviewStatus ? form.elements.reviewStatus.value : "";
      filters.promotion_state = form.elements.promotionState ? form.elements.promotionState.value : "";
      filters.tag = form.elements.tag ? form.elements.tag.value.trim() : "";
      filters.actor_agent_id = form.elements.actorAgentId ? form.elements.actorAgentId.value.trim() : "";
    }
    return filters;
  }

  function refreshMemory(searchTerm) {
    var qs = query(memorySearchFilters(searchTerm));
    return api("/api/matm/search?" + qs).then(function (payload) {
      render("[data-console-memory-output]", payload);
      renderMemorySummary(payload);
      return payload;
    });
  }

  function refreshInbox(agentId) {
    var requestedAgent = agentId || state.agentId;
    var qs = query({workspace_id: state.workspaceId, agent_id: requestedAgent});
    return api("/api/matm/current-message?" + qs).then(function (payload) {
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstNotificationId = first && first.notification ? first.notification.notificationId : "";
      state.visibleNotificationIds = ((payload && payload.items) || []).map(function (item) {
        return item.notification && item.notification.notificationId;
      }).filter(Boolean);
      render("[data-console-inbox-output]", payload);
      renderInboxSummary(payload, requestedAgent);
      return payload;
    });
  }

  function refreshLaneOverview() {
    if (!state.workspaceId) {
      renderLaneOverview([]);
      return Promise.resolve([]);
    }
    var checks = agentLanes.map(function (lane) {
      var qs = query({workspace_id: state.workspaceId, agent_id: lane.agentId});
      return api("/api/matm/current-message?" + qs).then(function (payload) {
        return {
          ok: true,
          label: lane.label,
          agentId: lane.agentId,
          payload: payload,
        };
      }).catch(function (error) {
        return {
          ok: false,
          label: lane.label,
          agentId: lane.agentId,
          error: error.message,
          payload: {items: [], unreadCount: 0},
        };
      });
    });
    return Promise.all(checks).then(function (results) {
      renderLaneOverview(results);
      return results;
    });
  }

  function setInboxAgent(agentId) {
    if (!agentId) {
      return;
    }
    state.agentId = agentId;
    var form = pick("[data-console-inbox]");
    if (form && form.elements.agentId) {
      form.elements.agentId.value = agentId;
    }
    renderSessionSummary(state.workspace);
  }

  function openInboxLane(agentId, label) {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before refreshing inbox lanes."));
    }
    setInboxAgent(agentId);
    return refreshInbox(agentId).then(function () {
      setStatus((label || agentId) + " refreshed.", false);
    });
  }

  function refreshReceipts() {
    var consumerAgentId = state.agentId;
    var form = pick("[data-console-receipts-filter]");
    if (form && form.elements.consumerAgentId && form.elements.consumerAgentId.value) {
      consumerAgentId = form.elements.consumerAgentId.value;
    }
    var qs = query({workspace_id: state.workspaceId, consumer_agent_id: consumerAgentId});
    return api("/api/matm/receipts?" + qs).then(function (payload) {
      payload.filters = payload.filters || {};
      if (!payload.filters.consumerAgentId) {
        payload.filters.consumerAgentId = consumerAgentId;
      }
      render("[data-console-receipts-output]", payload);
      renderReceiptSummary(payload);
      return payload;
    });
  }

  function refreshAudit() {
    var params = {workspace_id: state.workspaceId};
    var form = pick("[data-console-audit-filter]");
    if (form) {
      var selectedLimit = form.elements.limit ? form.elements.limit.value : "50";
      params.action = form.elements.action ? form.elements.action.value : "";
      params.limit = selectedLimit === "50" ? "" : selectedLimit;
    }
    var qs = query(params);
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
        .then(function () { return refreshLaneOverview(); })
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
        .then(function (payload) {
          render("[data-console-memory-output]", payload);
          renderMemorySubmissionSummary(payload);
          return payload;
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

  var clearSearchFiltersButton = pick("[data-console-clear-search-filters]");
  if (clearSearchFiltersButton && searchForm) {
    clearSearchFiltersButton.addEventListener("click", function () {
      ["scope", "memoryType", "reviewStatus", "promotionState", "tag", "actorAgentId"].forEach(function (field) {
        if (searchForm.elements[field]) {
          searchForm.elements[field].value = "";
        }
      });
      refreshMemory(searchForm.elements.query.value)
        .then(function () { setStatus("Memory search filters cleared.", false); })
        .catch(function (error) { setStatus(error.message, true); });
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
        .then(function (payload) {
          if (target) {
            setInboxAgent(target);
            renderMessageDelivery(payload, target);
            return refreshInbox(target).then(refreshLaneOverview).then(function () { return payload; });
          }
          renderMessageDelivery(payload, state.agentId);
          return refreshInbox(state.agentId).then(refreshLaneOverview).then(function () { return payload; });
        })
        .then(function () { setStatus(target ? "Targeted message sent; " + target + " inbox refreshed." : "Broadcast message sent; current inbox refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var targetButtons = consoleRoot.querySelectorAll("[data-console-target-agent]");
  if (targetButtons.length && messageForm) {
    Array.prototype.forEach.call(targetButtons, function (button) {
      button.addEventListener("click", function () {
        var target = button.getAttribute("data-console-target-agent") || "";
        messageForm.elements.targetAgentId.value = target;
        setStatus(target ? button.textContent + " selected as target." : "Broadcast selected.", false);
      });
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
          renderReviewDecisionSummary(payload);
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
      setInboxAgent(inboxForm.elements.agentId.value.trim() || state.agentId);
      refreshInbox(state.agentId).catch(function (error) { setStatus(error.message, true); });
    });
  }

  var inboxLaneButtons = consoleRoot.querySelectorAll("[data-console-inbox-agent]");
  if (inboxLaneButtons.length) {
    Array.prototype.forEach.call(inboxLaneButtons, function (button) {
      button.addEventListener("click", function () {
        var agentId = button.getAttribute("data-console-inbox-agent") || "";
        openInboxLane(agentId, button.textContent)
          .catch(function (error) { setStatus(error.message, true); });
      });
    });
  }

  var refreshLanesButton = pick("[data-console-refresh-lanes]");
  if (refreshLanesButton) {
    refreshLanesButton.addEventListener("click", function () {
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before refreshing all lanes.", true);
        return;
      }
      refreshLaneOverview()
        .then(function () { setStatus("All inbox lanes refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var ackButton = pick("[data-console-ack]");
  function ackNotification(notificationId, idempotencySuffix) {
    return api("/api/matm/notifications/ack", {
      method: "POST",
      headers: {"Idempotency-Key": "console-ack-" + notificationId + (idempotencySuffix || "")},
      body: {
        workspaceId: state.workspaceId,
        notificationId: notificationId,
        consumerAgentId: state.agentId,
        status: "read",
      },
    });
  }

  if (ackButton) {
    ackButton.addEventListener("click", function () {
      if (!state.firstNotificationId) {
        setStatus("No unread notification is selected.", true);
        return;
      }
      ackNotification(state.firstNotificationId, "")
        .then(function (payload) {
          renderAcknowledgementSummary(payload);
          return payload;
        })
        .then(function () { return refreshInbox(state.agentId); })
        .then(refreshReceipts)
        .then(refreshLaneOverview)
        .then(function () { setStatus("Notification acknowledged and receipt refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var ackVisibleButton = pick("[data-console-ack-visible]");
  if (ackVisibleButton) {
    ackVisibleButton.addEventListener("click", function () {
      var notificationIds = state.visibleNotificationIds.slice();
      if (!notificationIds.length) {
        setStatus("No visible unread notifications are selected.", true);
        return;
      }
      var chain = Promise.resolve();
      var ackPayloads = [];
      notificationIds.forEach(function (notificationId) {
        chain = chain.then(function () {
          return ackNotification(notificationId, "-visible").then(function (payload) {
            ackPayloads.push(payload);
            return payload;
          });
        });
      });
      chain
        .then(function () {
          renderAcknowledgementSummary({
            receipts: ackPayloads.map(function (payload) {
              return payload.receipt;
            }).filter(Boolean),
          });
        })
        .then(function () { return refreshInbox(state.agentId); })
        .then(refreshReceipts)
        .then(refreshLaneOverview)
        .then(function () { setStatus(notificationIds.length + " visible notification(s) acknowledged and receipts refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var receiptsButton = pick("[data-console-receipts]");
  if (receiptsButton) {
    receiptsButton.addEventListener("click", function () {
      refreshReceipts().catch(function (error) { setStatus(error.message, true); });
    });
  }

  var clearReceiptsFilterButton = pick("[data-console-clear-receipts-filter]");
  if (clearReceiptsFilterButton) {
    clearReceiptsFilterButton.addEventListener("click", function () {
      var form = pick("[data-console-receipts-filter]");
      if (form && form.elements.consumerAgentId) {
        form.elements.consumerAgentId.value = "";
      }
      refreshReceipts()
        .then(function () { setStatus("Receipt filter cleared.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var receiptsFilterForm = pick("[data-console-receipts-filter]");
  if (receiptsFilterForm && receiptsFilterForm.elements.consumerAgentId) {
    receiptsFilterForm.elements.consumerAgentId.addEventListener("change", function () {
      refreshReceipts()
        .then(function () { setStatus("Receipts refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var auditButton = pick("[data-console-audit]");
  if (auditButton) {
    auditButton.addEventListener("click", function () {
      refreshAudit().catch(function (error) { setStatus(error.message, true); });
    });
  }

  var auditFilterForm = pick("[data-console-audit-filter]");
  if (auditFilterForm) {
    auditFilterForm.addEventListener("submit", function (event) {
      event.preventDefault();
      refreshAudit()
        .then(function () { setStatus("Audit log refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var clearAuditFilterButton = pick("[data-console-clear-audit-filter]");
  if (clearAuditFilterButton && auditFilterForm) {
    clearAuditFilterButton.addEventListener("click", function () {
      auditFilterForm.elements.action.value = "";
      auditFilterForm.elements.limit.value = "50";
      refreshAudit()
        .then(function () { setStatus("Audit filter cleared.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }
})();
