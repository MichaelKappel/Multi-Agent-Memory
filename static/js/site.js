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
    debugJson: false,
    workspaceOperatorSummary: null,
    agentRegistrationSummary: null,
    selectedMeetingRoomId: "",
    latestMeetingMessageId: "",
    inboxRequestSeq: 0,
    memoryCount: null,
    memoryScopeCounts: null,
    memoryFilesystemIncluded: false,
    reviewCount: null,
    meetingRoomCount: null,
    inboxUnreadCount: null,
    laneUnreadCount: null,
    messageDeliveryCounts: null,
    receiptCount: null,
    auditCount: null,
    receiptsPayloadsHidden: null,
    auditCredentialsHidden: null,
    auditPayloadsHidden: null,
  };
  var agentLanes = [
    { agentId: "human-verifier-agent", label: "Human" },
    { agentId: "codex-agent", label: "Codex" },
    { agentId: "swarm-observer-agent", label: "Observer" },
  ];
  var longTermMemoryTag = "long-term-memory-migration";

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

  function setDebugJsonVisible(visible) {
    state.debugJson = Boolean(visible);
    consoleRoot.classList.toggle("debug-json-hidden", !state.debugJson);
    var toggle = pick("[data-console-debug-toggle]");
    if (toggle) {
      toggle.checked = state.debugJson;
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

  function appendCountBadges(parent, label, counts, preferredKeys) {
    counts = counts || {};
    var keys = (preferredKeys || []).slice();
    Object.keys(counts).forEach(function (key) {
      if (keys.indexOf(key) === -1) {
        keys.push(key);
      }
    });
    var active = keys.filter(function (key) {
      return counts[key];
    });
    if (!active.length) {
      return;
    }
    parent.appendChild(el("span", "filter-summary-label", label));
    active.forEach(function (key) {
      appendBadge(parent, key + ": " + counts[key], "neutral");
    });
  }

  function renderMemoryOperatorSummary(parent, payload, items) {
    var summary = (payload && payload.operatorSummary) || {};
    var count = summary.count !== undefined ? summary.count : (items || []).length;
    var line = el("div", "filter-summary memory-search-summary");
    line.appendChild(el("span", "filter-summary-label", "Summary"));
    appendBadge(line, count + " hosted", count ? "good" : "neutral");
    appendBadge(line, summary.filesystemDocsIncluded ? "filesystem included" : "filesystem excluded", summary.filesystemDocsIncluded ? "warn" : "good");
    appendCountBadges(line, "Scopes", summary.scopeCounts, ["account", "company", "workspace", "project"]);
    appendCountBadges(line, "Reviews", summary.reviewStatusCounts, ["pending", "quarantined", "promoted", "rejected"]);
    appendCountBadges(line, "Promotion", summary.promotionStateCounts, ["review_pending", "quarantined", "promoted", "rejected"]);
    parent.appendChild(line);
  }

  function operatorLevel(operatorSummary, level) {
    var hierarchy = (operatorSummary && operatorSummary.hierarchy) || [];
    for (var i = 0; i < hierarchy.length; i += 1) {
      if (hierarchy[i].level === level) {
        return hierarchy[i];
      }
    }
    return {};
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

  function surfaceInfo() {
    var hostname = window.location.hostname || "";
    var isLocal = hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
    return {
      isLocal: isLocal,
      label: isLocal ? "local site" : "live site",
      badge: isLocal ? "local" : "production",
      kind: isLocal ? "neutral" : "good",
      origin: window.location.origin || hostname,
    };
  }

  function updateSurfaceBadge() {
    var node = pick("[data-console-surface-badge]");
    if (!node) {
      return;
    }
    var surface = surfaceInfo();
    node.textContent = surface.badge;
    node.className = "status-badge " + surface.kind;
  }

  function countMeta(counts, preferredKeys) {
    counts = counts || {};
    var keys = (preferredKeys || []).slice();
    Object.keys(counts).forEach(function (key) {
      if (keys.indexOf(key) === -1) {
        keys.push(key);
      }
    });
    var parts = keys.filter(function (key) {
      return counts[key];
    }).map(function (key) {
      return key + " " + counts[key];
    });
    return parts.join(" / ");
  }

  function metricCard(title, value, meta, badges) {
    var card = el("article", "metric-card");
    card.appendChild(el("span", "summary-label", title));
    card.appendChild(el("strong", "", value || "Pending"));
    card.appendChild(el("span", "summary-meta", meta || "Awaiting data"));
    var badgeLine = el("div", "badge-line");
    (badges || []).forEach(function (badge) {
      appendBadge(badgeLine, badge.text, badge.kind);
    });
    if (badgeLine.childNodes.length) {
      card.appendChild(badgeLine);
    }
    return card;
  }

  function renderOperatorMetrics() {
    var node = pick("[data-console-operator-metrics]");
    if (!node) {
      return;
    }
    updateSurfaceBadge();
    clear(node);
    var surface = surfaceInfo();
    var boundaryReady = Boolean(state.workspaceOperatorSummary && state.workspaceOperatorSummary.hierarchyReady);
    var deliveryCounts = state.messageDeliveryCounts || {};
    var unreadCount = state.laneUnreadCount !== null && state.laneUnreadCount !== undefined
      ? state.laneUnreadCount
      : state.inboxUnreadCount;
    var evidencePending = state.receiptCount === null && state.auditCount === null;
    node.appendChild(metricCard(
      "Session",
      state.workspaceId ? "Workspace loaded" : "Awaiting key",
      surface.origin,
      [
        { text: surface.badge, kind: surface.kind },
        { text: state.workspaceId ? "key hidden" : "key masked", kind: "good" },
      ]
    ));
    node.appendChild(metricCard(
      "Boundary",
      boundaryReady ? "4 levels loaded" : "Boundary pending",
      "account / company / workspace / project",
      [
        { text: boundaryReady ? "pass" : "pending", kind: boundaryReady ? "good" : "neutral" },
      ]
    ));
    node.appendChild(metricCard(
      "Memory",
      state.memoryCount !== null && state.memoryCount !== undefined ? state.memoryCount + " item(s)" : "Search pending",
      countMeta(state.memoryScopeCounts, ["account", "company", "workspace", "project"]) || "hosted search",
      [
        { text: "hosted", kind: "good" },
        { text: state.memoryFilesystemIncluded ? "filesystem review" : "filesystem excluded", kind: state.memoryFilesystemIncluded ? "warn" : "good" },
      ]
    ));
    node.appendChild(metricCard(
      "Messages",
      unreadCount !== null && unreadCount !== undefined ? unreadCount + " unread" : "Inbox pending",
      countMeta(deliveryCounts, ["broadcast", "targeted"]) || "broadcast / targeted",
      [
        { text: "rows", kind: "neutral" },
      ]
    ));
    node.appendChild(metricCard(
      "Evidence",
      evidencePending ? "Evidence pending" : (state.receiptCount !== null && state.receiptCount !== undefined ? state.receiptCount : 0) + " receipts",
      evidencePending ? "receipts / audit" : (state.auditCount !== null && state.auditCount !== undefined ? state.auditCount : 0) + " audit events",
      [
        { text: state.auditCredentialsHidden === false ? "credential review" : "credentials hidden", kind: state.auditCredentialsHidden === false ? "warn" : "good" },
        { text: state.auditPayloadsHidden === false || state.receiptsPayloadsHidden === false ? "payload review" : "payloads hidden", kind: state.auditPayloadsHidden === false || state.receiptsPayloadsHidden === false ? "warn" : "good" },
      ]
    ));
  }

  function renderSessionSummary(workspace, operatorSummary) {
    var node = pick("[data-console-session-summary]");
    if (!node) {
      return;
    }
    clear(node);
    if (!workspace || !workspace.workspaceId) {
      node.appendChild(el("p", "empty-state", "Session status will appear after the workspace loads."));
      return;
    }
    var surface = surfaceInfo();
    var accountRaw = workspace.accounts && workspace.accounts.length ? workspace.accounts[0] : {};
    var companyRaw = workspace.company || {};
    var projectRaw = workspace.projects && workspace.projects.length ? workspace.projects[0] : {};
    var account = operatorLevel(operatorSummary, "account");
    var company = operatorLevel(operatorSummary, "company");
    var project = operatorLevel(operatorSummary, "project");
    var privacy = (operatorSummary && operatorSummary.privacy) || {};
    var agentSummary = state.agentRegistrationSummary || {};
    var hierarchyReady = operatorSummary && operatorSummary.hierarchyReady !== undefined ? operatorSummary.hierarchyReady : Boolean(
      (account.id || accountRaw.accountId || workspace.accountId) &&
      (company.id || companyRaw.companyId || workspace.companyId) &&
      workspace.workspaceId &&
      (project.id || projectRaw.projectId || workspace.primaryProjectId)
    );
    node.appendChild(sessionItem("Surface", surface.label, surface.origin, [
      { text: surface.badge, kind: surface.kind },
    ]));
    node.appendChild(sessionItem("Boundary", hierarchyReady ? "4 levels loaded" : "check boundary", "account -> company -> workspace -> project", [
      { text: hierarchyReady ? "pass" : "review", kind: hierarchyReady ? "good" : "warn" },
    ]));
    node.appendChild(sessionItem("Key", (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "review key handling" : "not echoed", "browser session only", [
      { text: (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "review" : "private", kind: (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "warn" : "good" },
    ]));
    node.appendChild(sessionItem("Agent", agentSummary.agentId || state.agentId, agentSummary.currentMessageLaneReady ? "current inbox lane ready" : "current inbox lane", [
      { text: agentSummary.registered ? "registered" : "active", kind: "good" },
      { text: agentSummary.rawCredentialExposed ? "credential exposure review" : "credentials hidden", kind: agentSummary.rawCredentialExposed ? "warn" : "good" },
      { text: agentSummary.rawPayloadExposed ? "payload exposure review" : "payload hidden", kind: agentSummary.rawPayloadExposed ? "warn" : "good" },
    ]));
    var actions = el("nav", "session-actions");
    actions.setAttribute("aria-label", "Loaded workspace shortcuts");
    [
      { href: "#memory-workflow", label: "Memory" },
      { href: "#meeting-rooms", label: "Meetings" },
      { href: "#message-lanes", label: "Messages" },
      { href: "#receipts-audit", label: "Receipts" },
    ].forEach(function (item) {
      var link = el("a", "button compact", item.label);
      link.href = item.href;
      actions.appendChild(link);
    });
    node.appendChild(actions);
    renderOperatorMetrics();
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

  function renderWorkspaceBoundaryChain(workspace, account, company, project, operatorSummary) {
    var chain = el("div", "boundary-chain");
    chain.appendChild(el("div", "result-count", "Boundary chain: account -> company -> workspace -> project"));
    var steps = el("div", "boundary-steps");
    var hierarchy = operatorSummary && operatorSummary.hierarchy && operatorSummary.hierarchy.length ? operatorSummary.hierarchy.map(function (item) {
      return {
        label: item.level.charAt(0).toUpperCase() + item.level.slice(1),
        value: item.id,
        status: item.status || "active",
        copyLabel: item.level.charAt(0).toUpperCase() + item.level.slice(1) + " id",
      };
    }) : [
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
    ];
    hierarchy.forEach(function (item) {
      steps.appendChild(boundaryStep(item.label, item.value, item.status, item.copyLabel));
    });
    chain.appendChild(steps);
    return chain;
  }

  function renderWorkspaceSummary(workspace, operatorSummary) {
    var node = pick("[data-console-workspace-summary]");
    if (!node) {
      return;
    }
    clear(node);
    if (!workspace || !workspace.workspaceId) {
      node.appendChild(el("p", "empty-state", "Workspace details will appear after the key is accepted."));
      return;
    }
    var accountRaw = workspace.accounts && workspace.accounts.length ? workspace.accounts[0] : {};
    var companyRaw = workspace.company || {};
    var projectRaw = workspace.projects && workspace.projects.length ? workspace.projects[0] : {};
    var account = operatorLevel(operatorSummary, "account");
    var company = operatorLevel(operatorSummary, "company");
    var workspaceLevel = operatorLevel(operatorSummary, "workspace");
    var project = operatorLevel(operatorSummary, "project");
    var storage = (operatorSummary && operatorSummary.storage) || {};
    var privacy = (operatorSummary && operatorSummary.privacy) || {};
    node.appendChild(renderWorkspaceBoundaryChain(workspace, accountRaw, companyRaw, projectRaw, operatorSummary));
    appendCopyActions(node.appendChild(summaryCard("Account", account.label || accountRaw.label || workspace.accountId, shortId(account.id || accountRaw.accountId || workspace.accountId), [
      { text: account.role || accountRaw.role || "owner", kind: "neutral" },
      { text: account.status || accountRaw.status || "active", kind: "good" },
    ])), [
      { label: "Copy account id", copyLabel: "Account id", value: account.id || accountRaw.accountId || workspace.accountId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Company", company.label || companyRaw.label || workspace.companyId, shortId(company.id || companyRaw.companyId || workspace.companyId), [
      { text: company.status || companyRaw.status || "active", kind: "good" },
    ])), [
      { label: "Copy company id", copyLabel: "Company id", value: company.id || companyRaw.companyId || workspace.companyId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Workspace", workspaceLevel.label || workspace.label || workspace.workspaceId, shortId(workspaceLevel.id || workspace.workspaceId), [
      { text: workspaceLevel.plan || workspace.plan || "plan unknown", kind: "neutral" },
      { text: workspaceLevel.status || workspace.status || "active", kind: "good" },
    ])), [
      { label: "Copy workspace id", copyLabel: "Workspace id", value: workspaceLevel.id || workspace.workspaceId },
    ]);
    appendCopyActions(node.appendChild(summaryCard("Project", project.label || projectRaw.label || workspace.primaryProjectId, shortId(project.id || projectRaw.projectId || workspace.primaryProjectId), [
      { text: project.status || projectRaw.status || "active", kind: "good" },
    ])), [
      { label: "Copy project id", copyLabel: "Project id", value: project.id || projectRaw.projectId || workspace.primaryProjectId },
    ]);
    node.appendChild(summaryCard(
      "Storage",
      formatBytes(storage.usedBytes !== undefined ? storage.usedBytes : workspace.storageUsedBytes) + " used",
      formatBytes(storage.remainingBytes !== undefined ? storage.remainingBytes : workspace.storageRemainingBytes) + " remaining",
      [{ text: (storage.quotaExceeded || workspace.quotaExceeded) ? "quota exceeded" : "within quota", kind: (storage.quotaExceeded || workspace.quotaExceeded) ? "warn" : "good" }]
    ));
    node.appendChild(summaryCard("Redaction", (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "Check key handling" : "Key not stored raw", "Values are public-safe", [
      { text: (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "review" : "pass", kind: (privacy.rawKeyStoredByServer || workspace.rawKeyStoredByServer) ? "warn" : "good" },
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
    var summary = (payload && payload.operatorSummary) || {};
    state.memoryCount = summary.count !== undefined ? summary.count : items.length;
    state.memoryScopeCounts = summary.scopeCounts || null;
    state.memoryFilesystemIncluded = Boolean(summary.filesystemDocsIncluded);
    renderOperatorMetrics();
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No hosted memory matched this search."));
      renderMemoryOperatorSummary(node, payload, items);
      appendFilterSummary(node, payload && payload.filters);
      return;
    }
    node.appendChild(el("div", "result-count", items.length + " hosted memory item(s). Filesystem docs are excluded from protected search."));
    renderMemoryOperatorSummary(node, payload, items);
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
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var submission = (payload && payload.submission) || {};
    var memoryId = operatorSummary.memoryEventId || submission.memoryEventId || event.eventId || "";
    if (!memoryId) {
      node.appendChild(el("p", "empty-state", "Saved memory confirmations will appear here."));
      return;
    }
    var firewall = event.firewall || {};
    var firewallDecision = operatorSummary.firewallDecision || submission.firewallDecision || firewall.decision || "accepted";
    var reviewStatus = operatorSummary.reviewStatus || submission.reviewStatus || event.reviewStatus || "pending";
    var summaryLine = el("div", "filter-summary memory-submit-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Saved memory"));
    appendBadge(summaryLine, operatorSummary.scope || submission.scope || event.scope || "workspace", "neutral");
    appendBadge(summaryLine, operatorSummary.memoryType || submission.memoryType || event.memoryType || "memory", "neutral");
    appendBadge(summaryLine, reviewStatus, reviewStatus === "quarantined" ? "warn" : "good");
    appendBadge(summaryLine, firewallDecision, firewallDecision === "quarantine_for_review" ? "warn" : "good");
    appendBadge(
      summaryLine,
      operatorSummary.rawPayloadExposed ? "payload exposure review" : "payload hidden",
      operatorSummary.rawPayloadExposed ? "warn" : "good"
    );
    appendBadge(
      summaryLine,
      operatorSummary.rawCredentialExposed ? "credential exposure review" : "credentials hidden",
      operatorSummary.rawCredentialExposed ? "warn" : "good"
    );
    var row = resultRow(
      "Memory saved",
      event.summary || "Memory event recorded without exposing raw private payloads.",
      [
        { text: operatorSummary.scope || submission.scope || event.scope || "workspace", kind: "neutral" },
        { text: operatorSummary.memoryType || submission.memoryType || event.memoryType || "memory", kind: "neutral" },
        { text: reviewStatus, kind: reviewStatus === "quarantined" ? "warn" : "good" },
        { text: firewallDecision, kind: firewallDecision === "quarantine_for_review" ? "warn" : "good" },
        { text: operatorSummary.valuesRedacted || submission.valuesRedacted ? "redacted" : "", kind: "good" },
        { text: operatorSummary.rawPayloadExposed || submission.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: operatorSummary.rawPayloadExposed || submission.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "memory " + shortId(memoryId),
        "review " + shortId(operatorSummary.reviewId || submission.reviewId || event.reviewId),
        "actor " + (operatorSummary.actorAgentId || event.actorAgentId || "unknown"),
        event.createdAt || "",
      ]
    );
    row.className += " submission-row";
    appendCopyActions(row, [
      { label: "Copy memory id", copyLabel: "Memory id", value: memoryId },
      { label: "Copy review id", copyLabel: "Review id", value: operatorSummary.reviewId || submission.reviewId || event.reviewId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(row);
  }

  function inboxAgentFromPayload(payload, fallback) {
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var filters = (payload && payload.filters) || {};
    var first = payload && payload.items && payload.items.length ? payload.items[0] : {};
    var delivery = first.delivery || {};
    var notification = first.notification || {};
    return operatorSummary.agentId || filters.agentId || delivery.inboxAgentId || notification.targetAgentId || fallback || state.agentId || "selected agent";
  }

  function renderInboxSummary(payload, agentId) {
    var node = pick("[data-console-inbox-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var lane = inboxAgentFromPayload(payload, agentId || state.agentId);
    appendFilterSummary(node, payload && payload.filters);
    var deliveryCounts = operatorSummary.deliveryCounts || (payload && payload.deliveryCounts) || {};
    var responseCounts = operatorSummary.responseDispositionCounts || {};
    state.inboxUnreadCount = operatorSummary.unreadCount !== undefined ? operatorSummary.unreadCount : items.length;
    state.messageDeliveryCounts = deliveryCounts;
    renderOperatorMetrics();
    var summaryLine = el("div", "filter-summary inbox-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Inbox"));
    appendBadge(summaryLine, (operatorSummary.unreadCount !== undefined ? operatorSummary.unreadCount : items.length) + " unread", items.length ? "warn" : "good");
    appendCountBadges(summaryLine, "Delivery", deliveryCounts, ["broadcast", "targeted"]);
    appendCountBadges(summaryLine, "Responses", responseCounts, ["required_response", "viewed_acknowledgement"]);
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No unread messages for " + lane + "."));
      return;
    }
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
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var delivery = (payload && payload.delivery) || {};
    var deliveryCounts = operatorSummary.deliveryCounts || (payload && payload.deliveryCounts) || {};
    var responseCounts = operatorSummary.responseDispositionCounts || {};
    var target = operatorSummary.targetAgentId || delivery.targetAgentId || message.targetAgentId || notification.targetAgentId || "";
    var messageType = operatorSummary.messageType || delivery.messageType || (target ? "targeted" : "broadcast");
    var responseDisposition = operatorSummary.responseDisposition || delivery.responseDisposition || notification.responseDisposition || "viewed_acknowledgement";
    var isTargeted = messageType === "targeted";
    var refreshedLane = refreshedAgentId || target || state.agentId;
    var summaryLine = el("div", "filter-summary delivery-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Delivery"));
    appendBadge(summaryLine, messageType, isTargeted ? "neutral" : "good");
    appendCountBadges(summaryLine, "Counts", deliveryCounts, ["broadcast", "targeted"]);
    appendCountBadges(summaryLine, "Responses", responseCounts, ["required_response", "viewed_acknowledgement"]);
    appendBadge(
      summaryLine,
      operatorSummary.rawPayloadExposed ? "payload exposure review" : "payload hidden",
      operatorSummary.rawPayloadExposed ? "warn" : "good"
    );
    appendBadge(
      summaryLine,
      operatorSummary.rawCredentialExposed ? "credential exposure review" : "credentials hidden",
      operatorSummary.rawCredentialExposed ? "warn" : "good"
    );
    var row = resultRow(
      isTargeted ? "Targeted message delivered" : "Broadcast delivered",
      message.safeSummary || "The message was accepted by the current-message lane.",
      [
        { text: messageType, kind: isTargeted ? "neutral" : "good" },
        { text: message.responseRequired ? "response required" : "ack only", kind: message.responseRequired ? "warn" : "neutral" },
        { text: operatorSummary.valuesRedacted || message.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "from " + (message.senderAgentId || "unknown"),
        "to " + (target || "all agents"),
        "delivery " + messageType,
        "response " + responseDisposition,
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
    node.appendChild(summaryLine);
    node.appendChild(el("div", "result-count", target ? refreshedLane + " inbox refreshed." : "Broadcast accepted; " + refreshedLane + " inbox refreshed."));
    node.appendChild(row);
  }

  function renderLaneOverview(results) {
    var node = pick("[data-console-lane-overview]");
    if (!node) {
      return;
    }
    clear(node);
    if (!results || !results.length) {
      state.laneUnreadCount = null;
      state.messageDeliveryCounts = null;
      renderOperatorMetrics();
      node.appendChild(el("p", "empty-state", "All-lane unread counts will appear after the workspace loads."));
      return;
    }
    var totalUnread = 0;
    var totalBroadcast = 0;
    var totalTargeted = 0;
    results.forEach(function (result) {
      var payload = result.payload || {};
      var items = payload.items || [];
      var deliveryCounts = payload.deliveryCounts || {};
      totalUnread += payload.unreadCount !== undefined ? payload.unreadCount : items.length;
      totalBroadcast += deliveryCounts.broadcast || 0;
      totalTargeted += deliveryCounts.targeted || 0;
    });
    state.laneUnreadCount = totalUnread;
    state.messageDeliveryCounts = {broadcast: totalBroadcast, targeted: totalTargeted};
    renderOperatorMetrics();
    node.appendChild(el("div", "result-count", results.length + " agent lane(s) checked."));
    results.forEach(function (result) {
      var payload = result.payload || {};
      var items = payload.items || [];
      var unreadCount = payload.unreadCount !== undefined ? payload.unreadCount : items.length;
      var deliveryCounts = payload.deliveryCounts || {};
      var broadcastCount = deliveryCounts.broadcast || 0;
      var targetedCount = deliveryCounts.targeted || 0;
      var first = items.length ? items[0].message || {} : {};
      var row = resultRow(
        result.label + " inbox",
        result.ok
          ? (items.length ? first.safeSummary : "No unread current messages.")
          : (result.error || "Lane refresh failed."),
        [
          { text: result.ok ? "reachable" : "error", kind: result.ok ? "good" : "warn" },
          { text: unreadCount + " unread", kind: unreadCount ? "warn" : "good" },
          { text: broadcastCount + " broadcast", kind: broadcastCount ? "good" : "neutral" },
          { text: targetedCount + " targeted", kind: targetedCount ? "neutral" : "good" },
        ],
        [
          "agent " + result.agentId,
          "delivery " + broadcastCount + " broadcast / " + targetedCount + " targeted",
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

  function setMeetingRoom(roomId) {
    if (!roomId) {
      return;
    }
    state.selectedMeetingRoomId = roomId;
    var form = pick("[data-console-meeting-message]");
    if (form && form.elements.roomId) {
      form.elements.roomId.value = roomId;
    }
  }

  function roomTitle(room) {
    return room.name || room.label || (room.scope ? room.scope + " meeting" : "Meeting room");
  }

  function renderMeetingRooms(payload) {
    var node = pick("[data-console-meeting-rooms-list]");
    if (!node) {
      return;
    }
    clear(node);
    var rooms = (payload && payload.items) || [];
    var summary = (payload && payload.operatorSummary) || {};
    state.meetingRoomCount = summary.count !== undefined ? summary.count : rooms.length;
    renderOperatorMetrics();
    var summaryLine = el("div", "filter-summary meeting-rooms-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Meeting rooms"));
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : rooms.length) + " rooms", rooms.length ? "good" : "neutral");
    appendCountBadges(summaryLine, "Scopes", summary.scopeCounts, ["company", "workspace", "project", "goal", "task"]);
    if (summary.filters && (summary.filters.scope || summary.filters.scopeId)) {
      appendBadge(summaryLine, "filter " + (summary.filters.scope || "any"), "neutral");
      if (summary.filters.scopeId) {
        appendBadge(summaryLine, "scope " + shortId(summary.filters.scopeId), "neutral");
      }
    }
    appendBadge(summaryLine, (summary.alwaysAvailableCount || 0) + " always available", summary.alwaysAvailableCount ? "good" : "warn");
    appendBadge(summaryLine, (summary.unreadCount || 0) + " unread", summary.unreadCount ? "warn" : "good");
    node.appendChild(summaryLine);
    if (!rooms.length) {
      node.appendChild(el("p", "empty-state", "No meeting rooms returned for this workspace."));
      return;
    }
    if (!state.selectedMeetingRoomId) {
      setMeetingRoom(rooms[0].roomId);
    }
    rooms.forEach(function (room) {
      var unread = room.unreadCount || 0;
      var row = resultRow(
        roomTitle(room),
        room.purpose || "Scoped agent coordination room.",
        [
          { text: room.scope || "room", kind: "neutral" },
          { text: unread + " unread", kind: unread ? "warn" : "good" },
          { text: (room.messageCount || 0) + " messages", kind: room.messageCount ? "good" : "neutral" },
          { text: room.alwaysAvailable ? "always available" : "review availability", kind: room.alwaysAvailable ? "good" : "warn" },
        ],
        [
          "room " + shortId(room.roomId),
          "scope " + (room.scopeId || "not set"),
          room.lastMessageAt ? "latest " + room.lastMessageAt : "latest none",
        ]
      );
      var actions = el("div", "row-actions");
      var openButton = el("button", "button compact", "Open room");
      var useButton = el("button", "button compact", "Use room");
      var copyButton = el("button", "button compact", "Copy room id");
      openButton.type = "button";
      useButton.type = "button";
      copyButton.type = "button";
      openButton.addEventListener("click", function () {
        setMeetingRoom(room.roomId);
        refreshMeetingMessages(room.roomId).catch(function (error) { setStatus(error.message, true); });
      });
      useButton.addEventListener("click", function () {
        setMeetingRoom(room.roomId);
        setStatus(roomTitle(room) + " selected.", false);
      });
      copyButton.addEventListener("click", function () {
        copySafeText(room.roomId, "Meeting room id");
      });
      actions.appendChild(openButton);
      actions.appendChild(useButton);
      actions.appendChild(copyButton);
      row.appendChild(actions);
      node.appendChild(row);
    });
  }

  function renderMeetingRoomCreate(payload) {
    var node = pick("[data-console-meeting-room-create-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var room = (payload && payload.room) || {};
    var summary = (payload && payload.operatorSummary) || {};
    if (!room.roomId) {
      node.appendChild(el("p", "empty-state", "Goal and task room creation confirmations will appear here."));
      return;
    }
    var summaryLine = el("div", "filter-summary meeting-room-create-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Room creation"));
    appendBadge(summaryLine, room.scope || "room", "neutral");
    appendBadge(summaryLine, payload.created ? "created" : "reused", payload.created ? "good" : "neutral");
    appendBadge(summaryLine, summary.alwaysAvailable ? "available" : "availability review", summary.alwaysAvailable ? "good" : "warn");
    appendBadge(summaryLine, summary.rawPayloadExposed ? "payload exposure review" : "payload hidden", summary.rawPayloadExposed ? "warn" : "good");
    var row = resultRow(
      payload.created ? "Meeting room created" : "Meeting room ready",
      room.purpose || "Goal or task coordination room is ready.",
      [
        { text: room.scope || "room", kind: "neutral" },
        { text: room.defaultRoom ? "default" : "custom", kind: room.defaultRoom ? "neutral" : "good" },
        { text: room.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "room " + shortId(room.roomId),
        "scope " + (room.scopeId || "not set"),
        "creator " + (summary.creatorAgentId || state.agentId),
        "route " + (summary.roomCreationRoute || "/api/matm/meeting-rooms"),
      ]
    );
    appendCopyActions(row, [
      { label: "Copy room id", copyLabel: "Meeting room id", value: room.roomId },
      { label: "Copy scope id", copyLabel: "Scope id", value: room.scopeId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(row);
  }

  function renderMeetingMessages(payload) {
    var node = pick("[data-console-meeting-messages-list]");
    if (!node) {
      return;
    }
    clear(node);
    var room = (payload && payload.room) || {};
    var items = (payload && payload.items) || [];
    var summary = (payload && payload.operatorSummary) || {};
    if (room.roomId) {
      setMeetingRoom(room.roomId);
    }
    state.latestMeetingMessageId = items.length ? items[items.length - 1].meetingMessageId : "";
    var summaryLine = el("div", "filter-summary meeting-messages-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Transcript"));
    appendBadge(summaryLine, roomTitle(room), "neutral");
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : items.length) + " messages", items.length ? "good" : "neutral");
    appendBadge(summaryLine, (summary.unreadCount || 0) + " unread", summary.unreadCount ? "warn" : "good");
    appendCountBadges(summaryLine, "Senders", summary.senderAgentCounts, []);
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No meeting messages in this room yet."));
      return;
    }
    items.forEach(function (message) {
      var row = resultRow(
        "Meeting message",
        message.safeSummary,
        [
          { text: message.scope || room.scope || "room", kind: "neutral" },
          { text: message.valuesRedacted ? "redacted" : "", kind: "good" },
          { text: message.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: message.rawPayloadExposed ? "warn" : "good" },
        ],
        [
          "sender " + (message.senderAgentId || "unknown"),
          "message " + shortId(message.meetingMessageId),
          "room " + shortId(message.roomId || room.roomId),
          message.createdAt || "",
        ]
      );
      appendCopyActions(row, [
        { label: "Copy meeting message id", copyLabel: "Meeting message id", value: message.meetingMessageId },
        { label: "Copy room id", copyLabel: "Meeting room id", value: message.roomId || room.roomId },
      ]);
      node.appendChild(row);
    });
  }

  function renderMeetingPost(payload) {
    var node = pick("[data-console-meeting-post-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var room = (payload && payload.room) || {};
    var message = (payload && payload.message) || {};
    var summary = (payload && payload.operatorSummary) || {};
    if (!message.meetingMessageId) {
      node.appendChild(el("p", "empty-state", "Meeting post confirmations will appear here."));
      return;
    }
    var summaryLine = el("div", "filter-summary meeting-post-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Meeting post"));
    appendBadge(summaryLine, summary.scope || room.scope || "room", "neutral");
    appendBadge(summaryLine, summary.alwaysAvailable ? "room available" : "availability review", summary.alwaysAvailable ? "good" : "warn");
    appendBadge(summaryLine, summary.rawPayloadExposed ? "payload exposure review" : "payload hidden", summary.rawPayloadExposed ? "warn" : "good");
    appendBadge(summaryLine, summary.rawCredentialExposed ? "credential exposure review" : "credentials hidden", summary.rawCredentialExposed ? "warn" : "good");
    var row = resultRow(
      "Meeting message posted",
      message.safeSummary || "Meeting message accepted.",
      [
        { text: room.scope || message.scope || "room", kind: "neutral" },
        { text: message.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "sender " + (message.senderAgentId || "unknown"),
        "message " + shortId(message.meetingMessageId),
        "room " + shortId(room.roomId || message.roomId),
      ]
    );
    appendCopyActions(row, [
      { label: "Copy meeting message id", copyLabel: "Meeting message id", value: message.meetingMessageId },
      { label: "Copy room id", copyLabel: "Meeting room id", value: room.roomId || message.roomId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(row);
  }

  function renderMeetingRead(payload) {
    var node = pick("[data-console-meeting-post-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var readState = (payload && payload.readState) || {};
    var room = (payload && payload.room) || {};
    var summary = (payload && payload.operatorSummary) || {};
    var row = resultRow(
      "Meeting room marked read",
      "Read cursor updated without exposing raw private payloads.",
      [
        { text: summary.status || readState.status || "read", kind: "good" },
        { text: summary.valuesRedacted || readState.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "agent " + (summary.agentId || readState.agentId || state.agentId),
        "room " + shortId(summary.roomId || readState.roomId || room.roomId),
        "last " + shortId(summary.lastMeetingMessageId || readState.lastMeetingMessageId),
        "read " + String(summary.readMessageCount || readState.readMessageCount || 0),
      ]
    );
    appendCopyActions(row, [
      { label: "Copy room id", copyLabel: "Meeting room id", value: summary.roomId || readState.roomId || room.roomId },
    ]);
    node.appendChild(row);
  }

  function renderReceiptSummary(payload) {
    var node = pick("[data-console-receipts-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    appendFilterSummary(node, payload && payload.filters);
    var summary = (payload && payload.operatorSummary) || {};
    state.receiptCount = summary.count !== undefined ? summary.count : items.length;
    state.receiptsPayloadsHidden = summary.allPayloadsHidden !== undefined ? summary.allPayloadsHidden : null;
    renderOperatorMetrics();
    var summaryLine = el("div", "filter-summary receipt-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Receipts"));
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : items.length) + " total", items.length ? "good" : "neutral");
    appendCountBadges(summaryLine, "Status", summary.statusCounts, ["read", "unread", "acknowledged"]);
    appendCountBadges(summaryLine, "Consumers", summary.consumerAgentCounts, []);
    appendBadge(summaryLine, summary.allPayloadsHidden === false ? "payload exposure review" : "payloads hidden", summary.allPayloadsHidden === false ? "warn" : "good");
    node.appendChild(summaryLine);
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
    var summaries = [];
    if (payload && payload.operatorSummary) {
      summaries.push(payload.operatorSummary);
    }
    if (payload && payload.operatorSummaries) {
      summaries = summaries.concat(payload.operatorSummaries);
    }
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
    var statusCounts = {};
    var rawPayloadExposedCount = 0;
    var allPayloadsHidden = true;
    var rawCredentialExposed = false;
    if (summaries.length) {
      summaries.forEach(function (summary) {
        Object.keys((summary && summary.statusCounts) || {}).forEach(function (status) {
          statusCounts[status] = (statusCounts[status] || 0) + summary.statusCounts[status];
        });
        if (summary && summary.rawPayloadExposedCount) {
          rawPayloadExposedCount += summary.rawPayloadExposedCount;
          allPayloadsHidden = false;
        }
        if (summary && summary.allPayloadsHidden === false) {
          allPayloadsHidden = false;
        }
        if (summary && summary.rawCredentialExposed) {
          rawCredentialExposed = true;
        }
      });
    } else {
      receipts.forEach(function (receipt) {
        var status = receipt.status || "read";
        statusCounts[status] = (statusCounts[status] || 0) + 1;
        if (receipt.rawPayloadExposed) {
          rawPayloadExposedCount += 1;
          allPayloadsHidden = false;
        }
        if (receipt.rawCredentialExposed) {
          rawCredentialExposed = true;
        }
      });
    }
    var summaryLine = el("div", "filter-summary ack-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Acknowledgement"));
    appendBadge(summaryLine, receipts.length + " recorded", "good");
    appendCountBadges(summaryLine, "Status", statusCounts, ["read"]);
    appendBadge(summaryLine, allPayloadsHidden ? "payloads hidden" : "payload exposure review", allPayloadsHidden ? "good" : "warn");
    appendBadge(summaryLine, rawCredentialExposed ? "credential exposure review" : "credentials hidden", rawCredentialExposed ? "warn" : "good");
    node.appendChild(summaryLine);
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
    var summary = (payload && payload.operatorSummary) || {};
    state.auditCount = summary.count !== undefined ? summary.count : items.length;
    state.auditCredentialsHidden = summary.allCredentialsHidden !== undefined ? summary.allCredentialsHidden : null;
    state.auditPayloadsHidden = summary.allPayloadsHidden !== undefined ? summary.allPayloadsHidden : null;
    renderOperatorMetrics();
    var summaryLine = el("div", "filter-summary audit-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Audit"));
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : items.length) + " events", items.length ? "good" : "neutral");
    appendCountBadges(summaryLine, "Actions", summary.actionCounts, ["memory.search", "message.submit", "meeting_room.create", "current_message.read", "notification.ack", "receipts.read", "audit_log.read"]);
    appendBadge(summaryLine, summary.allCredentialsHidden === false ? "credential exposure review" : "credentials hidden", summary.allCredentialsHidden === false ? "warn" : "good");
    appendBadge(summaryLine, summary.allPayloadsHidden === false ? "payload exposure review" : "payloads hidden", summary.allPayloadsHidden === false ? "warn" : "good");
    node.appendChild(summaryLine);
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
    appendFilterSummary(node, payload && payload.filters);
    var summary = (payload && payload.operatorSummary) || {};
    state.reviewCount = summary.count !== undefined ? summary.count : items.length;
    renderOperatorMetrics();
    var statusCounts = summary.statusCounts || (payload && payload.statusCounts) || {};
    var summaryLine = el("div", "filter-summary review-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Reviews"));
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : items.length) + " visible", items.length ? "warn" : "neutral");
    appendCountBadges(summaryLine, "Status", statusCounts, ["pending", "quarantined", "promoted", "rejected"]);
    appendCountBadges(summaryLine, "Firewall", summary.firewallDecisionCounts, ["accepted", "quarantine_for_review"]);
    if (summary.detectedThreatCount !== undefined) {
      appendBadge(summaryLine, summary.detectedThreatCount + " threats", summary.detectedThreatCount ? "warn" : "good");
    }
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No review queue items matched this status."));
      return;
    }
    var countText = items.length + " review item(s).";
    if (statusCounts.pending !== undefined || statusCounts.quarantined !== undefined || statusCounts.promoted !== undefined || statusCounts.rejected !== undefined) {
      countText += " " + (statusCounts.pending || 0) + " pending, " + (statusCounts.quarantined || 0) + " quarantined, " + (statusCounts.promoted || 0) + " promoted, " + (statusCounts.rejected || 0) + " rejected.";
    }
    node.appendChild(el("div", "result-count", countText));
    items.forEach(function (item) {
      var threats = item.detectedThreats || [];
      var metaItems = [
        "proposed by " + (item.proposedByAgentId || "unknown"),
        "review " + shortId(item.reviewId),
        "memory " + shortId(item.memoryEventId),
        "risk " + String(item.riskScore || 0),
        threats.length ? "threats " + threats.slice(0, 3).join(", ") : "",
        item.createdAt || "",
      ];
      var row = resultRow(
        "Review " + shortId(item.reviewId),
        item.publicSafeSummary || "No public-safe summary returned.",
        [
          { text: item.status || "pending", kind: item.status === "promoted" ? "good" : (item.status === "quarantined" ? "warn" : "neutral") },
          { text: item.firewallDecision || "review", kind: item.firewallDecision === "quarantine_for_review" ? "warn" : "good" },
          { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
        ],
        metaItems
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
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var reviewId = operatorSummary.reviewId || review.reviewId || "";
    if (!reviewId) {
      node.appendChild(el("p", "empty-state", "Review decisions will appear as operator confirmation rows."));
      return;
    }
    var status = operatorSummary.status || review.status || "recorded";
    var summaryLine = el("div", "filter-summary review-decision-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Review decision"));
    appendBadge(summaryLine, status, status === "promoted" ? "good" : (status === "quarantined" ? "warn" : "neutral"));
    appendCountBadges(summaryLine, "Status", operatorSummary.statusCounts, ["promoted", "rejected", "quarantined"]);
    appendBadge(
      summaryLine,
      operatorSummary.reviewNoteExposed ? "review note exposure" : "review note hidden",
      operatorSummary.reviewNoteExposed ? "warn" : "good"
    );
    appendBadge(
      summaryLine,
      operatorSummary.rawPayloadExposed ? "payload exposure review" : "payload hidden",
      operatorSummary.rawPayloadExposed ? "warn" : "good"
    );
    appendBadge(
      summaryLine,
      operatorSummary.rawCredentialExposed ? "credential exposure review" : "credentials hidden",
      operatorSummary.rawCredentialExposed ? "warn" : "good"
    );
    var row = resultRow(
      "Review decision " + status,
      "Decision recorded without exposing the raw review note.",
      [
        { text: status, kind: status === "promoted" ? "good" : (status === "quarantined" ? "warn" : "neutral") },
        { text: operatorSummary.valuesRedacted || review.valuesRedacted ? "redacted" : "", kind: "good" },
        { text: operatorSummary.rawPayloadExposed || review.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: operatorSummary.rawPayloadExposed || review.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "review " + shortId(reviewId),
        "memory " + shortId(operatorSummary.memoryEventId || review.memoryEventId),
        "reviewer " + (operatorSummary.reviewerAgentId || review.reviewerAgentId || "unknown"),
        operatorSummary.decidedAt || review.decidedAt || review.updatedAt || "",
      ]
    );
    appendCopyActions(row, [
      { label: "Copy review id", copyLabel: "Review id", value: reviewId },
      { label: "Copy memory id", copyLabel: "Memory id", value: operatorSummary.memoryEventId || review.memoryEventId },
    ]);
    node.appendChild(summaryLine);
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
      state.workspaceOperatorSummary = payload.operatorSummary || null;
      render("[data-console-workspace]", workspace);
      renderSessionSummary(workspace, state.workspaceOperatorSummary);
      renderWorkspaceSummary(workspace, state.workspaceOperatorSummary);
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
    }).then(function (payload) {
      state.agentRegistrationSummary = payload.operatorSummary || null;
      renderSessionSummary(state.workspace, state.workspaceOperatorSummary);
      return payload;
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

  function showHostedLongTermMemory() {
    if (!state.key || !state.workspaceId) {
      setStatus("Load workspace before searching hosted long-term memory.", true);
      return Promise.resolve(null);
    }
    var form = pick("[data-console-search]");
    if (form) {
      form.elements.query.value = longTermMemoryTag;
      ["scope", "memoryType", "reviewStatus", "promotionState", "actorAgentId"].forEach(function (field) {
        if (form.elements[field]) {
          form.elements[field].value = "";
        }
      });
      if (form.elements.tag) {
        form.elements.tag.value = longTermMemoryTag;
      }
    }
    return refreshMemory(longTermMemoryTag).then(function (payload) {
      var count = payload && payload.operatorSummary && payload.operatorSummary.count !== undefined
        ? payload.operatorSummary.count
        : ((payload && payload.items) || []).length;
      setStatus("Hosted long-term memory search refreshed: " + count + " item(s).", false);
      return payload;
    });
  }

  function refreshInbox(agentId) {
    var requestedAgent = agentId || state.agentId;
    var requestSeq = state.inboxRequestSeq += 1;
    var qs = query({workspace_id: state.workspaceId, agent_id: requestedAgent});
    return api("/api/matm/current-message?" + qs).then(function (payload) {
      if (requestSeq !== state.inboxRequestSeq) {
        return null;
      }
      var resolvedAgent = inboxAgentFromPayload(payload, requestedAgent);
      setInboxAgent(resolvedAgent);
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstNotificationId = first && first.notification ? first.notification.notificationId : "";
      state.visibleNotificationIds = ((payload && payload.items) || []).map(function (item) {
        return item.notification && item.notification.notificationId;
      }).filter(Boolean);
      render("[data-console-inbox-output]", payload);
      renderInboxSummary(payload, resolvedAgent);
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

  function refreshMeetingRooms() {
    if (!state.workspaceId) {
      renderMeetingRooms({items: [], operatorSummary: {count: 0}});
      return Promise.resolve({items: []});
    }
    var params = {workspace_id: state.workspaceId, agent_id: state.agentId};
    var filterForm = pick("[data-console-meeting-room-filter]");
    if (filterForm) {
      params.scope = filterForm.elements.scope ? filterForm.elements.scope.value : "";
      params.scope_id = filterForm.elements.scopeId ? filterForm.elements.scopeId.value.trim() : "";
    }
    var qs = query(params);
    return api("/api/matm/meeting-rooms?" + qs).then(function (payload) {
      render("[data-console-meeting-output]", payload);
      renderMeetingRooms(payload);
      if (!state.selectedMeetingRoomId && payload.items && payload.items.length) {
        setMeetingRoom(payload.items[0].roomId);
      }
      return payload;
    });
  }

  function refreshMeetingMessages(roomId) {
    var selectedRoom = roomId || state.selectedMeetingRoomId;
    if (!selectedRoom) {
      renderMeetingMessages({items: [], room: {}, operatorSummary: {count: 0}});
      return Promise.resolve({items: []});
    }
    setMeetingRoom(selectedRoom);
    var qs = query({workspace_id: state.workspaceId, room_id: selectedRoom, agent_id: state.agentId, limit: 50});
    return api("/api/matm/meeting-messages?" + qs).then(function (payload) {
      render("[data-console-meeting-output]", payload);
      renderMeetingMessages(payload);
      return payload;
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
    renderSessionSummary(state.workspace, state.workspaceOperatorSummary);
  }

  function openInboxLane(agentId, label) {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before refreshing inbox lanes."));
    }
    setInboxAgent(agentId);
    return refreshInbox(agentId).then(function (payload) {
      if (!payload) {
        return null;
      }
      var resolvedAgent = inboxAgentFromPayload(payload, agentId);
      setStatus((label || resolvedAgent + " inbox") + " refreshed.", false);
      return payload;
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
  var debugToggle = pick("[data-console-debug-toggle]");
  setDebugJsonVisible(debugToggle ? debugToggle.checked : false);
  updateSurfaceBadge();
  renderOperatorMetrics();
  if (debugToggle) {
    debugToggle.addEventListener("change", function () {
      setDebugJsonVisible(debugToggle.checked);
      setStatus(debugToggle.checked ? "Debug JSON visible." : "Operator view active.", false);
    });
  }

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
        .then(function () { return refreshMeetingRooms(); })
        .then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); })
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

  var longTermMemoryButton = pick("[data-console-long-term-memory]");
  if (longTermMemoryButton) {
    longTermMemoryButton.addEventListener("click", function () {
      showHostedLongTermMemory().catch(function (error) {
        setStatus(error.message, true);
      });
    });
  }

  var refreshMeetingRoomsButton = pick("[data-console-refresh-meeting-rooms]");
  if (refreshMeetingRoomsButton) {
    refreshMeetingRoomsButton.addEventListener("click", function () {
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before refreshing meeting rooms.", true);
        return;
      }
      refreshMeetingRooms()
        .then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); })
        .then(function () { setStatus("Meeting rooms refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var meetingRoomFilterForm = pick("[data-console-meeting-room-filter]");
  if (meetingRoomFilterForm) {
    meetingRoomFilterForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before filtering meeting rooms.", true);
        return;
      }
      state.selectedMeetingRoomId = "";
      refreshMeetingRooms()
        .then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); })
        .then(function () { setStatus("Meeting rooms filtered.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var clearMeetingRoomFilterButton = pick("[data-console-clear-meeting-room-filter]");
  if (clearMeetingRoomFilterButton && meetingRoomFilterForm) {
    clearMeetingRoomFilterButton.addEventListener("click", function () {
      meetingRoomFilterForm.elements.scope.value = "";
      meetingRoomFilterForm.elements.scopeId.value = "";
      state.selectedMeetingRoomId = "";
      refreshMeetingRooms()
        .then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); })
        .then(function () { setStatus("Meeting room filter cleared.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var createMeetingRoomForm = pick("[data-console-create-meeting-room]");
  if (createMeetingRoomForm) {
    createMeetingRoomForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before creating a meeting room.", true);
        return;
      }
      var scope = createMeetingRoomForm.elements.scope.value;
      var scopeId = createMeetingRoomForm.elements.scopeId.value.trim();
      if (!scopeId) {
        setStatus("Scope id is required for goal and task meeting rooms.", true);
        return;
      }
      api("/api/matm/meeting-rooms", {
        method: "POST",
        headers: {"Idempotency-Key": "console-meeting-room-" + scope + "-" + scopeId + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          creatorAgentId: createMeetingRoomForm.elements.creatorAgentId.value.trim() || state.agentId,
          scope: scope,
          scopeId: scopeId,
          name: createMeetingRoomForm.elements.name.value.trim(),
          purpose: createMeetingRoomForm.elements.purpose.value.trim(),
        },
      })
        .then(function (payload) {
          renderMeetingRoomCreate(payload);
          if (payload.room && payload.room.roomId) {
            setMeetingRoom(payload.room.roomId);
            if (meetingRoomFilterForm) {
              meetingRoomFilterForm.elements.scope.value = payload.room.scope || "";
              meetingRoomFilterForm.elements.scopeId.value = payload.room.scopeId || "";
            }
          }
          return refreshMeetingRooms().then(function () {
            return refreshMeetingMessages(state.selectedMeetingRoomId);
          });
        })
        .then(function () { setStatus("Meeting room created and selected.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var meetingMessageForm = pick("[data-console-meeting-message]");
  if (meetingMessageForm) {
    meetingMessageForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var roomId = meetingMessageForm.elements.roomId.value.trim() || state.selectedMeetingRoomId;
      if (!roomId) {
        setStatus("Meeting room id is required.", true);
        return;
      }
      setMeetingRoom(roomId);
      api("/api/matm/meeting-messages", {
        method: "POST",
        headers: {"Idempotency-Key": "console-meeting-" + roomId + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          roomId: roomId,
          senderAgentId: meetingMessageForm.elements.senderAgentId.value.trim(),
          safeSummary: meetingMessageForm.elements.safeSummary.value.trim(),
        },
      })
        .then(function (payload) {
          renderMeetingPost(payload);
          return refreshMeetingRooms().then(function () { return refreshMeetingMessages(roomId); });
        })
        .then(function () { setStatus("Meeting message posted and room refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var markMeetingReadButton = pick("[data-console-mark-meeting-read]");
  if (markMeetingReadButton) {
    markMeetingReadButton.addEventListener("click", function () {
      if (!state.selectedMeetingRoomId) {
        setStatus("Select a meeting room before marking it read.", true);
        return;
      }
      api("/api/matm/meeting-rooms/read", {
        method: "POST",
        headers: {"Idempotency-Key": "console-meeting-read-" + state.selectedMeetingRoomId + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          roomId: state.selectedMeetingRoomId,
          agentId: state.agentId,
          lastMeetingMessageId: state.latestMeetingMessageId,
        },
      })
        .then(function (payload) {
          renderMeetingRead(payload);
          return refreshMeetingRooms().then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); });
        })
        .then(function () { setStatus("Meeting room marked read.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var messageForm = pick("[data-console-message]");
  if (messageForm) {
    messageForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var target = messageForm.elements.targetAgentId.value.trim();
      var refreshedLane = target || state.agentId;
      var body = {
        workspaceId: state.workspaceId,
        senderAgentId: messageForm.elements.senderAgentId.value.trim(),
        safeSummary: messageForm.elements.safeSummary.value.trim(),
        responseRequired: messageForm.elements.responseRequired.checked,
      };
      if (target) {
        body.targetAgentId = target;
        setInboxAgent(target);
        renderEmpty("[data-console-inbox-list]", "Refreshing " + target + " inbox after delivery.");
      }
      setStatus(target ? "Sending targeted message to " + target + "." : "Sending broadcast message.", false);
      api("/api/matm/agent-messages", {
        method: "POST",
        headers: {"Idempotency-Key": "console-message-" + Date.now()},
        body: body,
      })
        .then(function (payload) {
          setStatus("Message accepted; refreshing " + refreshedLane + " inbox.", false);
          return refreshInbox(refreshedLane).then(function (inboxPayload) {
            var actualLane = inboxAgentFromPayload(inboxPayload, refreshedLane);
            renderMessageDelivery(payload, actualLane);
            return refreshLaneOverview().then(function () {
              return {deliveryPayload: payload, refreshedLane: actualLane};
            });
          });
        })
        .then(function (result) {
          var actualLane = (result && result.refreshedLane) || refreshedLane;
          setStatus(target ? "Targeted message sent; " + actualLane + " inbox refreshed." : "Broadcast message sent; " + actualLane + " inbox refreshed.", false);
        })
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
            operatorSummaries: ackPayloads.map(function (payload) {
              return payload.operatorSummary;
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
