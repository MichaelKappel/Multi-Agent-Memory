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
    visibleNotificationRecords: {},
    lastAckedBroadcast: null,
    firstReviewId: "",
    debugJson: false,
    workflowView: "workspace",
    runtimeVersion: null,
    runtimeVersionError: "",
    workspaceOperatorSummary: null,
    agentRegistrationSummary: null,
    selectedMeetingRoomId: "",
    selectedMeetingRoom: null,
    latestMeetingMessageId: "",
    latestMeetingMessageSummary: "",
    latestRoutingDecisionId: "",
    inboxRequestSeq: 0,
    memoryCount: null,
    memoryScopeCounts: null,
    memoryFilesystemIncluded: false,
    reviewCount: null,
    meetingRoomCount: null,
    inboxUnreadCount: null,
    inboxTotalUnreadCount: null,
    inboxCountLimited: false,
    laneUnreadCount: null,
    messageDeliveryCounts: null,
    messageRequiredResponseCount: null,
    receiptCount: null,
    auditCount: null,
    syncCapabilityStatus: null,
    syncDeviceStatus: null,
    syncLatestMutationStatus: "",
    syncLatestLogicalMemoryId: "",
    syncLastReadbackKind: "",
    syncLastReadbackCount: null,
    syncLatestDeviceId: "",
    syncLatestReceiptId: "",
    syncLatestRevisionId: "",
    syncLatestServerSequence: null,
    syncHeadCount: null,
    receiptsPayloadsHidden: null,
    auditCredentialsHidden: null,
    auditPayloadsHidden: null,
    longTermMemoryHealth: null,
    latestMemoryItems: [],
    latestInboxItems: [],
    latestLaneInboxItems: [],
    messageDeskMode: "focused",
    latestReceiptItems: [],
    latestAuditItems: [],
    latestReviewItems: [],
  };
  var agentLanes = [
    { agentId: "human-verifier-agent", label: "Human" },
    { agentId: "codex-agent", label: "Codex" },
    { agentId: "MemoryEndpoints-Backend-Agent", label: "Backend" },
    { agentId: "swarm-observer-agent", label: "Observer" },
  ];
  var longTermMemoryTag = "long-term-memory-migration";
  var longTermMemorySourcePrefix = "docs/long-term-memory/";
  var workflowLabels = {
    all: "All",
    workspace: "Workspace",
    memory: "Memory",
    sync: "Sync",
    reviews: "Reviews",
    meetings: "Meetings",
    messages: "Messages",
    evidence: "Evidence",
  };
  var workflowViewByHash = {
    "#workspace-overview": "workspace",
    "#memory-workflow": "memory",
    "#sync-workflow": "sync",
    "#review-queue": "reviews",
    "#meeting-rooms": "meetings",
    "#message-lanes": "messages",
    "#receipts-audit": "evidence",
  };
  var defaultWorkflowView = consoleRoot.getAttribute("data-console-default-workflow") || "workspace";

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

  function workflowPanel(view) {
    var panels = consoleRoot.querySelectorAll("[data-console-workflow-target]");
    for (var i = 0; i < panels.length; i += 1) {
      if (panels[i].getAttribute("data-console-workflow-target") === view) {
        return panels[i];
      }
    }
    return null;
  }

  function setWorkflowView(view, shouldScroll) {
    var resolved = workflowLabels[view] ? view : "all";
    var panels = consoleRoot.querySelectorAll("[data-console-workflow-target]");
    state.workflowView = resolved;
    consoleRoot.setAttribute("data-console-active-workflow", resolved);
    Array.prototype.forEach.call(panels, function (panel) {
      var target = panel.getAttribute("data-console-workflow-target");
      panel.hidden = resolved !== "all" && target !== resolved;
    });
    Array.prototype.forEach.call(consoleRoot.querySelectorAll("[data-console-workflow-view]"), function (button) {
      var active = button.getAttribute("data-console-workflow-view") === resolved;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    if (shouldScroll && resolved !== "all") {
      var panel = workflowPanel(resolved);
      if (panel && panel.scrollIntoView) {
        panel.scrollIntoView({block: "start"});
      }
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

  function formControl(form, name) {
    if (!form || !form.elements) {
      return null;
    }
    if (form.elements.namedItem) {
      return form.elements.namedItem(name);
    }
    return form.elements[name] || null;
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
    renderLongTermMemoryOperatorSummary(parent, summary.longTermMemoryMigration);
  }

  function formatStatusText(value) {
    return String(value || "unknown").replace(/_/g, " ");
  }

  function reviewStateKind(status) {
    if (status === "promoted" || status === "approved") {
      return "good";
    }
    if (status === "quarantined" || status === "rejected") {
      return "warn";
    }
    return "neutral";
  }

  function renderLongTermMemoryOperatorSummary(parent, migration) {
    if (!migration) {
      return;
    }
    var line = el("div", "filter-summary long-term-memory-summary");
    line.appendChild(el("span", "filter-summary-label", "Long-term memory"));
    appendBadge(line, formatStatusText(migration.status), migration.status === "promoted" ? "good" : "warn");
    appendBadge(line, (migration.searchResultCount || 0) + " search hits", migration.searchResultCount ? "neutral" : "good");
    appendBadge(line, (migration.canonicalSourceCount || migration.count || 0) + " canonical sources", (migration.canonicalSourceCount || migration.count) ? "good" : "neutral");
    appendBadge(line, (migration.sourcePathCount || 0) + " source paths", migration.sourcePathCount ? "good" : "neutral");
    appendBadge(line, (migration.canonicalRecordCount || migration.recordCount || migration.count || 0) + " canonical records", (migration.canonicalRecordCount || migration.recordCount) ? "neutral" : "good");
    if (migration.relatedRecordCount) {
      appendBadge(line, migration.relatedRecordCount + " related records excluded from canonical", "neutral");
    }
    if (migration.duplicateRecordCount) {
      appendBadge(line, migration.duplicateRecordCount + " duplicate records", "warn");
    }
    appendBadge(line, migration.filesystemDocsIncluded ? "filesystem included" : "filesystem excluded", migration.filesystemDocsIncluded ? "warn" : "good");
    appendBadge(line, migration.allValuesRedacted ? "redacted" : "redaction review", migration.allValuesRedacted ? "good" : "warn");
    appendBadge(line, migration.rawPrivatePayloadStoredCount ? "payload storage review" : "private payload hidden", migration.rawPrivatePayloadStoredCount ? "warn" : "good");
    appendCountBadges(line, "Reviews", migration.reviewStatusCounts, ["pending", "quarantined", "promoted", "rejected"]);
    appendCountBadges(line, "Promotion", migration.promotionStateCounts, ["review_pending", "quarantined", "promoted", "rejected"]);
    appendCountBadges(line, "Related reviews", migration.relatedReviewStatusCounts, ["pending", "quarantined", "promoted", "rejected"]);
    parent.appendChild(line);
  }

  function isLongTermMemoryHealthPayload(payload) {
    var filters = (payload && payload.filters) || {};
    return filters.tag === longTermMemoryTag
      || filters.sourcePrefix === longTermMemorySourcePrefix
      || filters.source_prefix === longTermMemorySourcePrefix;
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

  function runtimeEvidence() {
    var payload = state.runtimeVersion || {};
    var build = payload.build || {};
    var sourceSha = build.sourceShaShort || (build.sourceSha ? build.sourceSha.slice(0, 12) : "");
    var backend = payload.storeBackend || "";
    var backendStatus = payload.storeBackendStatus || "";
    var backendVerified = payload.storeBackendVerified === true;
    if (!state.runtimeVersion) {
      return {
        value: state.runtimeVersionError ? "Runtime review" : "Runtime pending",
        meta: state.runtimeVersionError || "/api/version",
        badges: [
          { text: state.runtimeVersionError ? "version unavailable" : "version pending", kind: state.runtimeVersionError ? "warn" : "neutral" },
        ],
      };
    }
    return {
      value: sourceSha ? "source " + sourceSha : "source pending",
      meta: [backend || "backend unknown", backendStatus].filter(Boolean).join(" / "),
      badges: [
        { text: "/api/version", kind: payload.ok === false ? "warn" : "neutral" },
        { text: backendVerified ? "backend verified" : "backend pending", kind: backendVerified ? "good" : "warn" },
      ],
    };
  }

  function refreshRuntimeVersion() {
    return fetch("/api/version", {
      method: "GET",
      headers: {"Accept": "application/json"},
      cache: "no-store",
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok) {
          var detail = payload.error && payload.error.detail ? payload.error.detail : "Request failed.";
          throw new Error(detail);
        }
        return payload;
      });
    })
      .then(function (payload) {
        state.runtimeVersion = payload;
        state.runtimeVersionError = "";
        if (state.workspace && state.workspace.workspaceId) {
          renderSessionSummary(state.workspace, state.workspaceOperatorSummary);
        } else {
          renderOperatorMetrics();
        }
        return payload;
      })
      .catch(function (error) {
        state.runtimeVersionError = error && error.message ? error.message : "Could not read /api/version.";
        renderOperatorMetrics();
        return null;
      });
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

  function checklistStatus(status, text) {
    return {status: status, text: text};
  }

  function checklistRow(title, status, detail, meta) {
    var row = el("article", "checklist-row");
    var badgeKind = status.status === "pass" ? "good" : (status.status === "review" ? "warn" : "neutral");
    var top = el("div", "checklist-row-top");
    top.appendChild(el("strong", "", title));
    appendBadge(top, status.text, badgeKind);
    row.appendChild(top);
    row.appendChild(el("p", "result-summary", detail));
    if (meta) {
      row.appendChild(el("span", "summary-meta", meta));
    }
    return row;
  }

  function isRequiredResponseItem(item) {
    var message = (item && item.message) || {};
    var delivery = (item && item.delivery) || {};
    var notification = (item && item.notification) || {};
    return Boolean(message.responseRequired)
      || delivery.responseDisposition === "required_response"
      || notification.responseDisposition === "required_response";
  }

  function requiredResponseCountFromPayload(payload, items) {
    var operatorSummary = (payload && payload.operatorSummary) || {};
    var responseCounts = operatorSummary.responseDispositionCounts || {};
    if (responseCounts.required_response !== undefined) {
      return responseCounts.required_response;
    }
    return (items || []).filter(isRequiredResponseItem).length;
  }

  function inboxPayloadIsFilteredOrLimited(payload) {
    var filters = (payload && payload.filters) || {};
    return Boolean(filters.limit || filters.messageId || filters.notificationId || filters.message_id || filters.notification_id);
  }

  function attentionFirstItems(items) {
    return (items || []).map(function (item, index) {
      return { item: item, index: index };
    }).sort(function (left, right) {
      var leftRank = isRequiredResponseItem(left.item) ? 0 : 1;
      var rightRank = isRequiredResponseItem(right.item) ? 0 : 1;
      return leftRank === rightRank ? left.index - right.index : leftRank - rightRank;
    }).map(function (entry) {
      return entry.item;
    });
  }

  function renderVerifierChecklist() {
    var node = pick("[data-console-verifier-checklist]");
    if (!node) {
      return;
    }
    clear(node);
    var boundaryReady = Boolean(state.workspaceOperatorSummary && state.workspaceOperatorSummary.hierarchyReady);
    var memoryKnown = state.memoryCount !== null && state.memoryCount !== undefined;
    var unreadKnown = state.laneUnreadCount !== null && state.laneUnreadCount !== undefined;
    var deliveryCounts = state.messageDeliveryCounts || {};
    var requiredResponseKnown = state.messageRequiredResponseCount !== null && state.messageRequiredResponseCount !== undefined;
    var requiredResponseCount = requiredResponseKnown ? state.messageRequiredResponseCount : 0;
    var broadcastSeen = Boolean(deliveryCounts.broadcast);
    var targetedSeen = Boolean(deliveryCounts.targeted);
    var receiptsKnown = state.receiptCount !== null && state.receiptCount !== undefined;
    var syncKnown = Boolean(state.syncCapabilityStatus || state.syncLatestReceiptId || state.syncLatestRevisionId || state.syncHeadCount !== null);
    var syncReady = Boolean(state.syncLatestReceiptId && state.syncHeadCount !== null);
    var redactionKnown = state.auditCredentialsHidden !== null && state.auditPayloadsHidden !== null && state.receiptsPayloadsHidden !== null;
    var redactionReview = state.auditCredentialsHidden === false || state.auditPayloadsHidden === false || state.receiptsPayloadsHidden === false;
    var header = el("div", "verifier-checklist-header");
    header.appendChild(el("span", "section-kicker", "Verifier Checklist"));
    appendBadge(header, state.workspaceId ? "operator status" : "waiting for workspace", state.workspaceId ? "neutral" : "neutral");
    node.appendChild(header);
    node.appendChild(checklistRow(
      "Workspace boundary",
      boundaryReady ? checklistStatus("pass", "pass") : checklistStatus("pending", "pending"),
      boundaryReady ? "Account, company, workspace, and project are loaded as operator cards." : "Load a workspace key to confirm the account/company/workspace/project hierarchy.",
      boundaryReady ? "4 hierarchy levels" : "boundary not loaded"
    ));
    node.appendChild(checklistRow(
      "Hosted memory",
      !memoryKnown ? checklistStatus("pending", "pending") : (state.memoryCount > 0 && !state.memoryFilesystemIncluded ? checklistStatus("pass", "pass") : checklistStatus("review", "review")),
      !memoryKnown ? "Run Search Verification or Hosted long-term memory." : (state.memoryCount + " hosted memory row(s); filesystem docs " + (state.memoryFilesystemIncluded ? "need review." : "excluded.")),
      countMeta(state.memoryScopeCounts, ["account", "company", "workspace", "project"]) || "memory search"
    ));
    node.appendChild(checklistRow(
      "Broadcast and targeted messages",
      !unreadKnown ? checklistStatus("pending", "pending") : (broadcastSeen && targetedSeen ? checklistStatus("pass", "pass") : checklistStatus("review", "review")),
      !unreadKnown ? "Refresh all lanes to distinguish broadcast from targeted messages." : ((deliveryCounts.broadcast || 0) + " broadcast / " + (deliveryCounts.targeted || 0) + " targeted visible across refreshed lanes."),
      unreadKnown ? state.laneUnreadCount + " unread across lanes" : "message lanes not refreshed"
    ));
    node.appendChild(checklistRow(
      "Direct attention",
      !requiredResponseKnown ? checklistStatus("pending", "pending") : (requiredResponseCount ? checklistStatus("review", "review") : checklistStatus("pass", "pass")),
      !requiredResponseKnown ? "Refresh the inbox or all lanes to detect targeted required-response work." : (requiredResponseCount ? requiredResponseCount + " required-response message(s) need operator action." : "No required-response messages are blocking the current operator view."),
      requiredResponseKnown ? "required response count" : "attention not checked"
    ));
    node.appendChild(checklistRow(
      "Receipts",
      !receiptsKnown ? checklistStatus("pending", "pending") : (state.receiptCount > 0 && state.receiptsPayloadsHidden !== false ? checklistStatus("pass", "pass") : checklistStatus("review", "review")),
      !receiptsKnown ? "Refresh receipts or acknowledge a visible notification." : (state.receiptCount + " receipt(s); payloads " + (state.receiptsPayloadsHidden === false ? "need review." : "hidden.")),
      "acknowledgement evidence"
    ));
    node.appendChild(checklistRow(
      "Distributed sync",
      !syncKnown ? checklistStatus("pending", "pending") : (syncReady ? checklistStatus("pass", "pass") : checklistStatus("review", "review")),
      !syncKnown ? "Refresh Sync capabilities, then register a device and submit a mutation." : (syncReady ? "Sync mutation receipt, change feed, and head readback are visible." : "Sync capability or mutation state is visible; complete readback to prove the path."),
      state.syncLatestReceiptId ? "receipt " + shortId(state.syncLatestReceiptId) : (state.syncCapabilityStatus || "sync workflow")
    ));
    node.appendChild(checklistRow(
      "Redaction",
      !redactionKnown ? checklistStatus("pending", "pending") : (redactionReview ? checklistStatus("review", "review") : checklistStatus("pass", "pass")),
      !redactionKnown ? "Refresh receipts and audit to verify hidden credentials and payloads." : (redactionReview ? "One redaction signal needs review." : "Credentials and private payloads are hidden in visible evidence."),
      "receipts / audit"
    ));
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
    var requiredResponseKnown = state.messageRequiredResponseCount !== null && state.messageRequiredResponseCount !== undefined;
    var requiredResponseCount = requiredResponseKnown ? state.messageRequiredResponseCount : 0;
    var showingLaneMessages = state.messageDeskMode === "lanes";
    var unreadCount = showingLaneMessages && state.laneUnreadCount !== null && state.laneUnreadCount !== undefined
      ? state.laneUnreadCount
      : state.inboxUnreadCount;
    var unreadTotal = showingLaneMessages ? null : state.inboxTotalUnreadCount;
    var unreadLabel = showingLaneMessages ? "unread" : (state.inboxCountLimited ? "visible unread" : "unread");
    var evidencePending = state.receiptCount === null && state.auditCount === null;
    var runtime = runtimeEvidence();
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
      "Runtime",
      runtime.value,
      runtime.meta,
      runtime.badges
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
      unreadCount !== null && unreadCount !== undefined ? unreadCount + " " + unreadLabel : "Inbox pending",
      !showingLaneMessages && state.inboxCountLimited && unreadTotal !== null && unreadTotal !== undefined && unreadTotal !== unreadCount
        ? unreadTotal + " total unread"
        : (countMeta(deliveryCounts, ["broadcast", "targeted"]) || "broadcast / targeted"),
      [
        { text: "rows", kind: "neutral" },
        { text: requiredResponseKnown ? (requiredResponseCount ? requiredResponseCount + " response needed" : "no response blockers") : "attention pending", kind: requiredResponseKnown ? (requiredResponseCount ? "warn" : "good") : "neutral" },
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
    renderVerifierChecklist();
    renderOperatorDesk();
    renderCommandBar();
  }

  function renderCommandBar() {
    var node = pick("[data-console-command-bar]");
    if (!node) {
      return;
    }
    var loaded = Boolean(state.workspaceId);
    var title = pick("[data-console-command-title]");
    var meta = pick("[data-console-command-meta]");
    if (title) {
      title.textContent = loaded ? "Workspace loaded" : "Workspace locked";
    }
    if (meta) {
      meta.textContent = loaded
        ? "Commands active for this workspace."
        : "Workspace key required.";
    }
    Array.prototype.forEach.call(node.querySelectorAll("[data-console-command]"), function (button) {
      button.disabled = !loaded;
      button.setAttribute("aria-disabled", loaded ? "false" : "true");
    });
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
    var runtime = runtimeEvidence();
    var hierarchyReady = operatorSummary && operatorSummary.hierarchyReady !== undefined ? operatorSummary.hierarchyReady : Boolean(
      (account.id || accountRaw.accountId || workspace.accountId) &&
      (company.id || companyRaw.companyId || workspace.companyId) &&
      workspace.workspaceId &&
      (project.id || projectRaw.projectId || workspace.primaryProjectId)
    );
    node.appendChild(sessionItem("Surface", surface.label, surface.origin, [
      { text: surface.badge, kind: surface.kind },
    ]));
    node.appendChild(sessionItem("Runtime", runtime.value, runtime.meta, runtime.badges));
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
      { href: "#sync-workflow", label: "Sync" },
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

  function deskPanel(selector, fallback) {
    var panel = pick(selector);
    if (!panel) {
      return null;
    }
    clear(panel);
    if (fallback) {
      panel.appendChild(el("p", "empty-state", fallback));
    }
    return panel;
  }

  function setOperatorDeskStatus(text, kind) {
    var node = pick("[data-console-operator-desk] .operator-desk-header .status-badge");
    if (node) {
      node.textContent = text;
      node.className = "status-badge " + (kind || "neutral");
    }
  }

  function appendDeskHeading(parent, title, meta) {
    var heading = el("div", "operator-desk-panel-heading");
    heading.appendChild(el("h3", "", title));
    if (meta) {
      heading.appendChild(el("span", "summary-meta", meta));
    }
    parent.appendChild(heading);
  }

  function renderDeskBoundary() {
    var panel = deskPanel("[data-console-desk-boundary]");
    if (!panel) {
      return;
    }
    appendDeskHeading(panel, "Hierarchy", state.workspaceId ? "copy-safe ids" : "locked");
    if (!state.workspace || !state.workspace.workspaceId) {
      panel.appendChild(el("p", "empty-state", "Account, company, workspace, and project cards appear after the key loads."));
      return;
    }
    var workspace = state.workspace;
    var operatorSummary = state.workspaceOperatorSummary || {};
    var accountRaw = workspace.accounts && workspace.accounts.length ? workspace.accounts[0] : {};
    var companyRaw = workspace.company || {};
    var projectRaw = workspace.projects && workspace.projects.length ? workspace.projects[0] : {};
    var account = operatorLevel(operatorSummary, "account");
    var company = operatorLevel(operatorSummary, "company");
    var workspaceLevel = operatorLevel(operatorSummary, "workspace");
    var project = operatorLevel(operatorSummary, "project");
    var cards = el("div", "operator-desk-cards");
    [
      {
        title: "Account",
        label: account.label || accountRaw.label || workspace.accountId,
        id: account.id || accountRaw.accountId || workspace.accountId,
        status: account.status || accountRaw.status || "active",
        copyLabel: "Account id",
      },
      {
        title: "Company",
        label: company.label || companyRaw.label || workspace.companyId,
        id: company.id || companyRaw.companyId || workspace.companyId,
        status: company.status || companyRaw.status || "active",
        copyLabel: "Company id",
      },
      {
        title: "Workspace",
        label: workspaceLevel.label || workspace.label || workspace.workspaceId,
        id: workspaceLevel.id || workspace.workspaceId,
        status: workspaceLevel.status || workspace.status || "active",
        copyLabel: "Workspace id",
      },
      {
        title: "Project",
        label: project.label || projectRaw.label || workspace.primaryProjectId,
        id: project.id || projectRaw.projectId || workspace.primaryProjectId,
        status: project.status || projectRaw.status || "active",
        copyLabel: "Project id",
      },
    ].forEach(function (item) {
      var card = summaryCard(item.title, item.label, shortId(item.id), [
        { text: item.status, kind: item.status === "active" ? "good" : "neutral" },
      ]);
      appendCopyActions(card, [
        { label: "Copy ID", copyLabel: item.copyLabel, value: item.id },
      ]);
      cards.appendChild(card);
    });
    panel.appendChild(cards);
  }

  function memoryDeskRow(item) {
    var row = resultRow(
      item.title || item.subject || "Hosted memory",
      item.summary || "Hosted memory record.",
      [
        { text: item.scope || "scope", kind: "neutral" },
        { text: item.memoryType || "memory", kind: "neutral" },
        { text: item.reviewStatus || item.promotionState || "review", kind: item.reviewStatus === "quarantined" ? "warn" : "good" },
        { text: item.valuesRedacted ? "redacted" : "public-safe", kind: "good" },
      ],
      [
        "memory " + shortId(item.eventId),
        "actor " + (item.actorAgentId || "unknown"),
        item.createdAt || "",
      ]
    );
    row.className += " operator-desk-row";
    return appendCopyActions(row, [
      { label: "Copy memory id", copyLabel: "Memory id", value: item.eventId },
    ]);
  }

  function longTermMemoryDeskRow(migration) {
    var sourceCount = migration.sourcePathCount || migration.canonicalSourceCount || migration.count || 0;
    var recordCount = migration.canonicalRecordCount || migration.recordCount || 0;
    var duplicateCount = migration.duplicateRecordCount || 0;
    var firstSource = migration.sourcePathSamples && migration.sourcePathSamples.length ? migration.sourcePathSamples[0] : "";
    var status = migration.status || "unknown";
    var row = resultRow(
      "Long-term memory health",
      "Hosted dogfood memory covers " + sourceCount + " source path(s) and " + recordCount + " canonical record(s).",
      [
        { text: formatStatusText(status), kind: status === "promoted" || migration.allPromoted ? "good" : "warn" },
        { text: sourceCount + " sources", kind: sourceCount ? "good" : "neutral" },
        { text: recordCount + " records", kind: recordCount ? "good" : "neutral" },
        { text: duplicateCount ? duplicateCount + " duplicates" : "no duplicates", kind: duplicateCount ? "warn" : "good" },
        { text: migration.filesystemDocsIncluded ? "filesystem review" : "filesystem excluded", kind: migration.filesystemDocsIncluded ? "warn" : "good" },
        { text: migration.allValuesRedacted ? "redacted" : "redaction review", kind: migration.allValuesRedacted ? "good" : "warn" },
        { text: migration.rawPrivatePayloadStoredCount ? "payload storage review" : "private payload hidden", kind: migration.rawPrivatePayloadStoredCount ? "warn" : "good" },
      ],
      [
        "store " + (migration.memorySource || "hosted_workspace_store"),
        "tag " + (migration.migrationTag || longTermMemoryTag),
        firstSource ? "sample " + firstSource : "",
      ]
    );
    row.className += " operator-desk-row long-term-memory-desk-row";
    return appendCopyActions(row, [
      { label: "Copy tag", copyLabel: "Long-term memory tag", value: migration.migrationTag || longTermMemoryTag },
      { label: "Copy source sample", copyLabel: "Long-term memory source", value: firstSource },
    ]);
  }

  function messageDeskRow(item) {
    var message = item.message || {};
    var notification = item.notification || {};
    var delivery = item.delivery || {};
    var laneRecipient = delivery.targetAgentId || message.targetAgentId || notification.targetAgentId;
    var messageType = delivery.messageType || (laneRecipient ? "targeted" : "broadcast");
    var laneLabel = item.operatorLaneLabel || "";
    var laneAgentId = item.operatorLaneAgentId || "";
    var row = resultRow(
      (laneLabel ? laneLabel + " lane: " : "") + (messageType === "targeted" ? "Targeted message" : "Broadcast message"),
      message.safeSummary || "Current-message row.",
      [
        { text: messageType, kind: messageType === "broadcast" ? "good" : "neutral" },
        { text: notification.status || "unread", kind: notification.status === "read" ? "good" : "warn" },
        { text: message.responseRequired ? "response required" : "viewed acknowledgement", kind: message.responseRequired ? "warn" : "neutral" },
        { text: message.valuesRedacted ? "redacted" : "public-safe", kind: "good" },
      ],
      [
        laneAgentId ? "lane " + laneAgentId : "",
        "from " + (message.senderAgentId || "unknown"),
        "to " + (laneRecipient || "all agents"),
        "message " + shortId(message.messageId),
        "notification " + shortId(notification.notificationId),
      ]
    );
    row.className += " operator-desk-row";
    return appendCopyActions(row, [
      { label: "Copy message id", copyLabel: "Message id", value: message.messageId },
      { label: "Copy notification id", copyLabel: "Notification id", value: notification.notificationId },
    ]);
  }

  function receiptDeskRow(item) {
    var row = resultRow(
      "Receipt " + (item.status || "read"),
      "Acknowledgement receipt; raw private payload remains hidden.",
      [
        { text: item.status || "read", kind: "good" },
        { text: item.valuesRedacted ? "redacted" : "public-safe", kind: "good" },
        { text: item.rawPayloadExposed ? "payload review" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "consumer " + (item.consumerAgentId || "unknown"),
        "receipt " + shortId(item.receiptId),
        "notification " + shortId(item.notificationId),
      ]
    );
    row.className += " operator-desk-row";
    return appendCopyActions(row, [
      { label: "Copy receipt id", copyLabel: "Receipt id", value: item.receiptId },
    ]);
  }

  function auditDeskRow(item) {
    var row = resultRow(
      item.action || "Audit event",
      "Actor " + (item.actor || "unknown") + " touched " + (item.target || "target") + ".",
      [
        { text: item.valuesRedacted ? "redacted" : "public-safe", kind: "good" },
        { text: item.rawCredentialExposed ? "credential review" : "credentials hidden", kind: item.rawCredentialExposed ? "warn" : "good" },
        { text: item.rawPayloadExposed ? "payload review" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "audit " + shortId(item.auditId),
        item.createdAt || "",
      ]
    );
    row.className += " operator-desk-row";
    return appendCopyActions(row, [
      { label: "Copy audit id", copyLabel: "Audit id", value: item.auditId },
    ]);
  }

  function syncDeskRow() {
    var hasSyncEvidence = Boolean(
      state.syncCapabilityStatus ||
      state.syncDeviceStatus ||
      state.syncLatestReceiptId ||
      state.syncLatestRevisionId ||
      state.syncHeadCount !== null
    );
    if (!hasSyncEvidence) {
      return null;
    }
    var status = state.syncLatestMutationStatus || state.syncDeviceStatus || state.syncCapabilityStatus || "ready";
    var sequence = state.syncLatestServerSequence !== null && state.syncLatestServerSequence !== undefined
      ? String(state.syncLatestServerSequence)
      : "pending";
    var readbackLabel = state.syncLastReadbackKind
      ? state.syncLastReadbackKind + " " + String(state.syncLastReadbackCount || 0)
      : "readback pending";
    var row = resultRow(
      "Distributed sync health",
      "Device authority, idempotent mutation receipts, and head readback are available from the operator console.",
      [
        { text: formatStatusText(status), kind: status === "applied" || status === "active" || status === "available" || status === "live" ? "good" : "neutral" },
        { text: state.syncCapabilityStatus || "capability pending", kind: state.syncCapabilityStatus ? "good" : "neutral" },
        { text: state.syncDeviceStatus || "device pending", kind: state.syncDeviceStatus === "revoked" ? "warn" : (state.syncDeviceStatus ? "good" : "neutral") },
        { text: "sequence " + sequence, kind: state.syncLatestServerSequence ? "good" : "neutral" },
        { text: readbackLabel, kind: state.syncLastReadbackCount ? "good" : "neutral" },
      ],
      [
        "device " + shortId(state.syncLatestDeviceId),
        "receipt " + shortId(state.syncLatestReceiptId),
        "revision " + shortId(state.syncLatestRevisionId),
        "logical " + (state.syncLatestLogicalMemoryId || "not set"),
        state.syncHeadCount !== null ? "heads " + String(state.syncHeadCount) : "",
      ]
    );
    row.className += " operator-desk-row sync-desk-row";
    return appendCopyActions(row, [
      { label: "Copy sync receipt id", copyLabel: "Sync receipt id", value: state.syncLatestReceiptId },
      { label: "Copy sync revision id", copyLabel: "Sync revision id", value: state.syncLatestRevisionId },
      { label: "Copy sync logical id", copyLabel: "Logical memory id", value: state.syncLatestLogicalMemoryId },
    ]);
  }

  function renderDeskMemory() {
    var panel = deskPanel("[data-console-desk-memory]");
    if (!panel) {
      return;
    }
    var items = state.latestMemoryItems || [];
    var migration = state.longTermMemoryHealth;
    appendDeskHeading(panel, "Memory Rows", migration ? "long-term health loaded" : (items.length ? items.length + " latest" : "search pending"));
    if (migration) {
      panel.appendChild(longTermMemoryDeskRow(migration));
    }
    if (!items.length) {
      panel.appendChild(el("p", "empty-state", "Recent hosted memory rows appear after search."));
      return;
    }
    items.slice(0, 3).forEach(function (item) {
      panel.appendChild(memoryDeskRow(item));
    });
  }

  function renderDeskMessages() {
    var panel = deskPanel("[data-console-desk-messages]");
    if (!panel) {
      return;
    }
    var showingLanes = state.messageDeskMode === "lanes";
    var items = showingLanes ? (state.latestLaneInboxItems || []) : (state.latestInboxItems || []);
    var knownUnread = showingLanes && state.laneUnreadCount !== null && state.laneUnreadCount !== undefined
      ? state.laneUnreadCount
      : items.length;
    var requiredResponseKnown = state.messageRequiredResponseCount !== null && state.messageRequiredResponseCount !== undefined;
    var requiredResponseCount = requiredResponseKnown ? state.messageRequiredResponseCount : 0;
    var headingMeta = requiredResponseKnown && requiredResponseCount
      ? requiredResponseCount + " response needed"
      : (showingLanes ? knownUnread + " unread across lanes" : (items.length ? items.length + (state.inboxCountLimited ? " visible unread" : " unread") : "inbox clear"));
    appendDeskHeading(panel, "Message Rows", headingMeta);
    if (!items.length) {
      panel.appendChild(el("p", "empty-state", showingLanes ? "All checked lanes are clear." : "Current-message rows appear after inbox refresh."));
      return;
    }
    items.slice(0, showingLanes ? 4 : 3).forEach(function (item) {
      panel.appendChild(messageDeskRow(item));
    });
  }

  function renderDeskEvidence() {
    var panel = deskPanel("[data-console-desk-evidence]");
    if (!panel) {
      return;
    }
    var receipts = state.latestReceiptItems || [];
    var audits = state.latestAuditItems || [];
    var syncRow = syncDeskRow();
    appendDeskHeading(panel, "Evidence", (receipts.length + audits.length || syncRow) ? receipts.length + " receipts / " + audits.length + " audit" + (syncRow ? " / sync" : "") : "refresh pending");
    if (!receipts.length && !audits.length && !syncRow) {
      panel.appendChild(el("p", "empty-state", "Receipt, audit, and sync evidence rows appear after refresh."));
      return;
    }
    if (syncRow) {
      panel.appendChild(syncRow);
    }
    receipts.slice(0, 2).forEach(function (item) {
      panel.appendChild(receiptDeskRow(item));
    });
    audits.slice(0, 2).forEach(function (item) {
      panel.appendChild(auditDeskRow(item));
    });
  }

  function renderOperatorDesk() {
    var root = pick("[data-console-operator-desk]");
    if (!root) {
      return;
    }
    var boundaryReady = Boolean(state.workspaceOperatorSummary && state.workspaceOperatorSummary.hierarchyReady);
    setOperatorDeskStatus(state.workspaceId ? (boundaryReady ? "ready" : "boundary review") : "workspace key required", state.workspaceId ? (boundaryReady ? "good" : "warn") : "neutral");
    renderDeskBoundary();
    renderDeskMemory();
    renderDeskMessages();
    renderDeskEvidence();
  }

  function renderMemorySummary(payload) {
    var node = pick("[data-console-memory-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    var summary = (payload && payload.operatorSummary) || {};
    state.latestMemoryItems = items.slice(0, 6);
    state.memoryCount = summary.count !== undefined ? summary.count : items.length;
    state.memoryScopeCounts = summary.scopeCounts || null;
    state.memoryFilesystemIncluded = Boolean(summary.filesystemDocsIncluded);
    if (summary.longTermMemoryMigration && isLongTermMemoryHealthPayload(payload)) {
      state.longTermMemoryHealth = summary.longTermMemoryMigration;
    }
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
    var confirmation = (payload && payload.confirmation) || {};
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
    appendBadge(summaryLine, payload.persisted || confirmation.persisted ? "readback confirmed" : "readback pending", payload.persisted || confirmation.persisted ? "good" : "warn");
    appendBadge(summaryLine, payload.visibleInSearch || confirmation.visibleInSearch ? "search visible" : "search pending", payload.visibleInSearch || confirmation.visibleInSearch ? "good" : "warn");
    appendBadge(summaryLine, payload.visibleInReviewQueue || confirmation.visibleInReviewQueue ? "review visible" : "review pending", payload.visibleInReviewQueue || confirmation.visibleInReviewQueue ? "good" : "warn");
    appendBadge(summaryLine, payload.visibleInAuditLog || confirmation.visibleInAuditLog ? "audit visible" : "audit pending", payload.visibleInAuditLog || confirmation.visibleInAuditLog ? "good" : "warn");
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
        { text: payload.persisted || confirmation.persisted ? "readback confirmed" : "readback pending", kind: payload.persisted || confirmation.persisted ? "good" : "warn" },
        { text: payload.visibleInAuditLog || confirmation.visibleInAuditLog ? "audit visible" : "audit pending", kind: payload.visibleInAuditLog || confirmation.visibleInAuditLog ? "good" : "warn" },
        { text: operatorSummary.valuesRedacted || submission.valuesRedacted ? "redacted" : "", kind: "good" },
        { text: operatorSummary.rawPayloadExposed || submission.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: operatorSummary.rawPayloadExposed || submission.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "memory " + shortId(memoryId),
        "review " + shortId(operatorSummary.reviewId || submission.reviewId || event.reviewId),
        "search " + (payload.visibleInSearch || confirmation.visibleInSearch ? "visible" : "pending"),
        "review queue " + (payload.visibleInReviewQueue || confirmation.visibleInReviewQueue ? "visible" : "pending"),
        "audit " + (payload.visibleInAuditLog || confirmation.visibleInAuditLog ? "visible" : "pending"),
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
    state.messageDeskMode = "focused";
    state.latestInboxItems = items.slice(0, 6);
    appendFilterSummary(node, payload && payload.filters);
    var deliveryCounts = operatorSummary.deliveryCounts || (payload && payload.deliveryCounts) || {};
    var responseCounts = operatorSummary.responseDispositionCounts || {};
    var inboxUnreadCount = operatorSummary.unreadCount !== undefined ? operatorSummary.unreadCount : items.length;
    var inboxTotalUnreadCount = operatorSummary.totalUnreadCount !== undefined
      ? operatorSummary.totalUnreadCount
      : ((payload && payload.totalUnreadCount !== undefined) ? payload.totalUnreadCount : inboxUnreadCount);
    var limitedInboxView = inboxPayloadIsFilteredOrLimited(payload);
    var inboxCountLabel = limitedInboxView ? "visible unread" : "unread";
    state.inboxUnreadCount = inboxUnreadCount;
    state.inboxTotalUnreadCount = inboxTotalUnreadCount;
    state.inboxCountLimited = limitedInboxView;
    state.messageDeliveryCounts = deliveryCounts;
    state.messageRequiredResponseCount = requiredResponseCountFromPayload(payload, items);
    renderOperatorMetrics();
    var summaryLine = el("div", "filter-summary inbox-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Inbox"));
    appendBadge(summaryLine, inboxUnreadCount + " " + inboxCountLabel, items.length ? "warn" : "good");
    if (limitedInboxView && inboxTotalUnreadCount !== inboxUnreadCount) {
      appendBadge(summaryLine, inboxTotalUnreadCount + " total unread", "neutral");
    }
    appendCountBadges(summaryLine, "Delivery", deliveryCounts, ["broadcast", "targeted"]);
    appendCountBadges(summaryLine, "Responses", responseCounts, ["required_response", "viewed_acknowledgement"]);
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No " + inboxCountLabel + " messages for " + lane + "."));
      return;
    }
    var countText = inboxUnreadCount + " " + inboxCountLabel + " message(s) for " + lane + ".";
    if (limitedInboxView && inboxTotalUnreadCount !== inboxUnreadCount) {
      countText += " " + inboxTotalUnreadCount + " total unread in this lane.";
    }
    if (deliveryCounts.broadcast !== undefined || deliveryCounts.targeted !== undefined) {
      countText += " " + (deliveryCounts.broadcast || 0) + " broadcast, " + (deliveryCounts.targeted || 0) + " targeted.";
    }
    node.appendChild(el("div", "result-count", countText));
    items.forEach(function (item) {
      var message = item.message || {};
      var notification = item.notification || {};
      var delivery = item.delivery || {};
      var laneRecipient = delivery.targetAgentId || message.targetAgentId || notification.targetAgentId;
      var messageType = delivery.messageType || (laneRecipient ? "targeted" : "broadcast");
      var isTargeted = messageType === "targeted";
      var target = isTargeted ? laneRecipient : "";
      var recipientText = isTargeted ? (target || "selected agent") : "all agents";
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
          "to " + recipientText,
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
    var laneRecipient = operatorSummary.targetAgentId || delivery.targetAgentId || message.targetAgentId || notification.targetAgentId || "";
    var messageType = operatorSummary.messageType || delivery.messageType || (laneRecipient ? "targeted" : "broadcast");
    var responseDisposition = operatorSummary.responseDisposition || delivery.responseDisposition || notification.responseDisposition || "viewed_acknowledgement";
    var isTargeted = messageType === "targeted";
    var target = isTargeted ? laneRecipient : "";
    var refreshedLane = refreshedAgentId || laneRecipient || state.agentId;
    var recipientText = isTargeted ? (target || "selected agent") : "all agents";
    var expectedRecipientCount = payload && payload.expectedRecipientCount !== undefined
      ? payload.expectedRecipientCount
      : (operatorSummary.recipientCount || delivery.recipientCount || ((payload && payload.notifications && payload.notifications.length) || 1));
    var visibleRecipientCount = payload && payload.visibleRecipientCount !== undefined
      ? payload.visibleRecipientCount
      : (payload && payload.visibleToTarget ? expectedRecipientCount : 0);
    var recipientReadbackText = visibleRecipientCount + "/" + expectedRecipientCount + " visible";
    var recipientReadbackOk = expectedRecipientCount > 0 && visibleRecipientCount >= expectedRecipientCount;
    var summaryLine = el("div", "filter-summary delivery-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Delivery"));
    appendBadge(summaryLine, messageType, isTargeted ? "neutral" : "good");
    if (!isTargeted) {
      appendBadge(summaryLine, expectedRecipientCount + " recipients", expectedRecipientCount > 1 ? "good" : "warn");
      appendBadge(summaryLine, recipientReadbackText, recipientReadbackOk ? "good" : "warn");
    }
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
        "to " + recipientText,
        "delivery " + messageType,
        "response " + responseDisposition,
        "message " + shortId(message.messageId),
        "notification " + shortId(notification.notificationId),
        isTargeted ? "" : "recipients " + recipientReadbackText,
        "refreshed " + refreshedLane + " inbox",
      ]
    );
    row.className += " delivery-row";
    appendCopyActions(row, [
      { label: "Copy message id", copyLabel: "Message id", value: message.messageId },
      { label: "Copy notification id", copyLabel: "Notification id", value: notification.notificationId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(el("div", "result-count", isTargeted ? refreshedLane + " inbox refreshed." : "Broadcast accepted; " + refreshedLane + " inbox refreshed."));
    node.appendChild(row);
  }

  function renderLaneOverview(results) {
    var node = pick("[data-console-lane-overview]");
    if (!node) {
      return;
    }
    clear(node);
    if (!results || !results.length) {
      state.messageDeskMode = "lanes";
      state.latestLaneInboxItems = [];
      state.laneUnreadCount = null;
      state.messageDeliveryCounts = null;
      state.messageRequiredResponseCount = null;
      renderOperatorMetrics();
      node.appendChild(el("p", "empty-state", "All-lane unread counts will appear after the workspace loads."));
      return;
    }
    var totalUnread = 0;
    var totalBroadcast = 0;
    var totalTargeted = 0;
    var totalRequiredResponse = 0;
    results.forEach(function (result) {
      var payload = result.payload || {};
      var items = payload.items || [];
      var deliveryCounts = payload.deliveryCounts || {};
      totalUnread += payload.unreadCount !== undefined ? payload.unreadCount : items.length;
      totalBroadcast += deliveryCounts.broadcast || 0;
      totalTargeted += deliveryCounts.targeted || 0;
      totalRequiredResponse += requiredResponseCountFromPayload(payload, items);
    });
    state.messageDeskMode = "lanes";
    state.latestLaneInboxItems = collectLaneInboxItems(results);
    state.laneUnreadCount = totalUnread;
    state.messageDeliveryCounts = {broadcast: totalBroadcast, targeted: totalTargeted};
    state.messageRequiredResponseCount = totalRequiredResponse;
    renderOperatorMetrics();
    node.appendChild(el("div", "result-count", results.length + " agent lane(s) checked."));
    renderBroadcastAckIsolationSummary(node, results);
    results.forEach(function (result) {
      var payload = result.payload || {};
      var items = payload.items || [];
      var unreadCount = payload.unreadCount !== undefined ? payload.unreadCount : items.length;
      var deliveryCounts = payload.deliveryCounts || {};
      var responseCounts = (payload.operatorSummary && payload.operatorSummary.responseDispositionCounts) || {};
      var broadcastCount = deliveryCounts.broadcast || 0;
      var targetedCount = deliveryCounts.targeted || 0;
      var requiredResponseCount = responseCounts.required_response !== undefined
        ? responseCounts.required_response
        : requiredResponseCountFromPayload(payload, items);
      var attentionItems = attentionFirstItems(items);
      var first = attentionItems.length ? attentionItems[0].message || {} : {};
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
          { text: requiredResponseCount + " response needed", kind: requiredResponseCount ? "warn" : "good" },
        ],
        [
          "agent " + result.agentId,
          "delivery " + broadcastCount + " broadcast / " + targetedCount + " targeted",
          "attention " + requiredResponseCount + " required response",
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

  function collectLaneInboxItems(results) {
    var rows = [];
    (results || []).forEach(function (result) {
      if (!result || !result.ok) {
        return;
      }
      var items = (result.payload && result.payload.items) || [];
      attentionFirstItems(items).slice(0, 2).forEach(function (item) {
        var row = {};
        Object.keys(item || {}).forEach(function (key) {
          row[key] = item[key];
        });
        row.operatorLaneAgentId = result.agentId;
        row.operatorLaneLabel = result.label;
        rows.push(row);
      });
    });
    return attentionFirstItems(rows).slice(0, 8);
  }

  function broadcastItemVisible(item, messageId) {
    var message = (item && item.message) || {};
    var delivery = (item && item.delivery) || {};
    var notification = (item && item.notification) || {};
    var type = delivery.messageType || (message.targetAgentId || notification.targetAgentId ? "targeted" : "broadcast");
    return type === "broadcast" && message.messageId === messageId;
  }

  function renderBroadcastAckIsolationSummary(parent, results) {
    var acked = state.lastAckedBroadcast || {};
    if (!acked.messageId) {
      return;
    }
    var checkedAgents = [];
    var visibleAgents = [];
    (results || []).forEach(function (result) {
      if (!result || !result.ok) {
        return;
      }
      checkedAgents.push(result.agentId);
      var items = (result.payload && result.payload.items) || [];
      if (items.some(function (item) { return broadcastItemVisible(item, acked.messageId); })) {
        visibleAgents.push(result.agentId);
      }
    });
    var remainingAgents = checkedAgents.filter(function (agentId) {
      return agentId !== acked.ackAgentId;
    });
    var missingAgents = remainingAgents.filter(function (agentId) {
      return visibleAgents.indexOf(agentId) === -1;
    });
    var ackedLaneCleared = visibleAgents.indexOf(acked.ackAgentId) === -1;
    var ok = remainingAgents.length > 0 && missingAgents.length === 0 && ackedLaneCleared;
    var line = el("div", "filter-summary broadcast-ack-isolation-summary");
    line.appendChild(el("span", "filter-summary-label", "Broadcast ack isolation"));
    appendBadge(line, ok ? "ack isolation pass" : "ack isolation review", ok ? "good" : "warn");
    appendBadge(line, visibleAgents.length + "/" + remainingAgents.length + " remaining lanes visible", ok ? "good" : "warn");
    appendBadge(line, ackedLaneCleared ? "acked lane cleared" : "acked lane still unread", ackedLaneCleared ? "good" : "warn");
    if (missingAgents.length) {
      appendBadge(line, "missing " + missingAgents.join(", "), "warn");
    }
    parent.appendChild(line);
  }

  function selectedMeetingRoomFallback(roomId) {
    return {roomId: roomId, name: "Selected meeting room", scope: "room", purpose: "Posts target the selected room id."};
  }

  function mergeMeetingRoomMetadata(roomId, room) {
    var existing = state.selectedMeetingRoom && state.selectedMeetingRoom.roomId === roomId ? state.selectedMeetingRoom : {};
    var fallback = selectedMeetingRoomFallback(roomId);
    var merged = {};
    [fallback, existing, room || {}].forEach(function (source) {
      Object.keys(source).forEach(function (key) {
        var value = source[key];
        if (value !== undefined && value !== null && value !== "") {
          merged[key] = value;
        }
      });
    });
    merged.roomId = roomId;
    return merged;
  }

  function renderSelectedMeetingRoom() {
    var node = pick("[data-console-selected-meeting-room]");
    if (!node) {
      return;
    }
    clear(node);
    var room = state.selectedMeetingRoom || {};
    if (!state.selectedMeetingRoomId) {
      node.appendChild(el("p", "empty-state", "Select a meeting room before posting or marking a transcript read."));
      return;
    }
    var row = resultRow(
      "Selected meeting room",
      room.purpose || "Posts target the selected room id.",
      [
        { text: room.scope || "room", kind: "neutral" },
        { text: (room.unreadCount || 0) + " unread", kind: room.unreadCount ? "warn" : "good" },
        { text: (room.messageCount || 0) + " messages", kind: room.messageCount ? "good" : "neutral" },
        { text: room.alwaysAvailable === false ? "availability review" : "available", kind: room.alwaysAvailable === false ? "warn" : "good" },
      ],
      [
        "room " + shortId(state.selectedMeetingRoomId),
        room.scopeId ? "scope " + room.scopeId : "",
        room.name || room.label || "",
      ]
    );
    row.className += " selected-meeting-room-row";
    appendCopyActions(row, [
      { label: "Copy selected room id", copyLabel: "Selected meeting room id", value: state.selectedMeetingRoomId },
    ]);
    node.appendChild(row);
  }

  function clearMeetingRoomSelection() {
    state.selectedMeetingRoomId = "";
    state.selectedMeetingRoom = null;
    var form = pick("[data-console-meeting-message]");
    if (form && form.elements.roomId) {
      form.elements.roomId.value = "";
    }
    renderSelectedMeetingRoom();
  }

  function setMeetingRoom(roomId, room) {
    if (!roomId) {
      return;
    }
    state.selectedMeetingRoomId = roomId;
    state.selectedMeetingRoom = mergeMeetingRoomMetadata(roomId, room && room.roomId ? room : {});
    var form = pick("[data-console-meeting-message]");
    if (form && form.elements.roomId) {
      form.elements.roomId.value = roomId;
    }
    var routingForm = pick("[data-console-routing-decision]");
    if (routingForm) {
      if (routingForm.elements.destinationRoomId && !routingForm.elements.destinationRoomId.value) {
        routingForm.elements.destinationRoomId.value = roomId;
      }
      if (routingForm.elements.sourceRoomId && !routingForm.elements.sourceRoomId.value) {
        routingForm.elements.sourceRoomId.value = roomId;
      }
    }
    renderSelectedMeetingRoom();
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
    var selectedRoom = rooms.filter(function (room) {
      return room.roomId === state.selectedMeetingRoomId;
    })[0];
    if (!state.selectedMeetingRoomId) {
      setMeetingRoom(rooms[0].roomId, rooms[0]);
    } else if (selectedRoom) {
      setMeetingRoom(selectedRoom.roomId, selectedRoom);
    } else {
      renderSelectedMeetingRoom();
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
        setMeetingRoom(room.roomId, room);
        refreshMeetingMessages(room.roomId).catch(function (error) { setStatus(error.message, true); });
      });
      useButton.addEventListener("click", function () {
        setMeetingRoom(room.roomId, room);
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

  function renderRoutingDecision(payload) {
    var node = pick("[data-console-routing-decision-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var decision = (payload && payload.routingDecision) || {};
    var summary = (payload && payload.operatorSummary) || {};
    var destination = (payload && payload.destinationRoom) || {};
    if (!decision.routingDecisionId) {
      node.appendChild(el("p", "empty-state", "Structured routing decisions will appear here."));
      return;
    }
    state.latestRoutingDecisionId = decision.routingDecisionId;
    var summaryLine = el("div", "filter-summary routing-decision-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Routing decision"));
    appendBadge(summaryLine, decision.lane || "lane", "neutral");
    appendBadge(summaryLine, summary.destinationScope || decision.destinationScope || "room", "neutral");
    appendBadge(summaryLine, payload.visibleToRoutedAgent ? "agent visible" : "visibility review", payload.visibleToRoutedAgent ? "good" : "warn");
    appendBadge(summaryLine, summary.rawPayloadExposed ? "payload exposure review" : "payload hidden", summary.rawPayloadExposed ? "warn" : "good");
    var evidence = decision.expectedEvidence || [];
    var row = resultRow(
      "Routing decision created",
      decision.specificGoal || "Agent has a structured route.",
      [
        { text: decision.lane || "lane", kind: "neutral" },
        { text: decision.status || "active", kind: "good" },
        { text: decision.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "agent " + (decision.routedAgentId || "unknown"),
        "coordinator " + (decision.coordinatorAgentId || state.agentId),
        "destination " + shortId(decision.destinationRoomId || destination.roomId),
        "decision " + shortId(decision.routingDecisionId),
        "message " + shortId(decision.meetingMessageId),
        evidence.length + " evidence items",
      ]
    );
    appendCopyActions(row, [
      { label: "Copy routing id", copyLabel: "Routing decision id", value: decision.routingDecisionId },
      { label: "Copy destination room", copyLabel: "Destination room id", value: decision.destinationRoomId || destination.roomId },
      { label: "Copy meeting message", copyLabel: "Meeting message id", value: decision.meetingMessageId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(row);
  }

  function renderRoutingDecisions(payload) {
    var node = pick("[data-console-routing-decisions-list]");
    if (!node) {
      return;
    }
    clear(node);
    var items = (payload && payload.items) || [];
    var summary = (payload && payload.operatorSummary) || {};
    var summaryLine = el("div", "filter-summary routing-decisions-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Routing readback"));
    appendBadge(summaryLine, (summary.count !== undefined ? summary.count : items.length) + " decisions", items.length ? "good" : "neutral");
    appendCountBadges(summaryLine, "Scopes", summary.destinationScopeCounts, ["company", "workspace", "project", "goal", "task"]);
    appendCountBadges(summaryLine, "Lanes", summary.laneCounts, []);
    appendBadge(summaryLine, summary.rawPayloadExposedCount ? "payload exposure review" : "payload hidden", summary.rawPayloadExposedCount ? "warn" : "good");
    appendFilterSummary(summaryLine, (payload && payload.filters) || {});
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No routing decisions match the current filters."));
      return;
    }
    items.forEach(function (decision) {
      var evidence = decision.expectedEvidence || [];
      var row = resultRow(
        "Routing for " + (decision.routedAgentId || "agent"),
        decision.specificGoal || decision.nextAction || "Structured routing decision.",
        [
          { text: decision.lane || "lane", kind: "neutral" },
          { text: decision.destinationScope || "room", kind: "neutral" },
          { text: decision.status || "active", kind: decision.status === "active" ? "good" : "neutral" },
        ],
        [
          "decision " + shortId(decision.routingDecisionId),
          "destination " + shortId(decision.destinationRoomId),
          "message " + shortId(decision.meetingMessageId),
          evidence.length + " evidence items",
          decision.createdAt || "",
        ]
      );
      appendCopyActions(row, [
        { label: "Copy routing id", copyLabel: "Routing decision id", value: decision.routingDecisionId },
        { label: "Copy destination room", copyLabel: "Destination room id", value: decision.destinationRoomId },
        { label: "Copy routed agent", copyLabel: "Routed agent id", value: decision.routedAgentId },
      ]);
      node.appendChild(row);
    });
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
      setMeetingRoom(room.roomId, room);
    }
    state.latestMeetingMessageId = items.length ? items[items.length - 1].meetingMessageId : "";
    state.latestMeetingMessageSummary = items.length ? (items[items.length - 1].safeSummary || "") : "";
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
      var promoteActions = el("div", "row-actions");
      var promoteButton = el("button", "button compact", "Save as memory");
      promoteButton.type = "button";
      promoteButton.addEventListener("click", function () {
        promoteMeetingMessage(message).catch(function (error) { setStatus(error.message, true); });
      });
      promoteActions.appendChild(promoteButton);
      row.appendChild(promoteActions);
      node.appendChild(row);
    });
  }

  function renderMeetingPromotion(payload) {
    var node = pick("[data-console-meeting-promote-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var event = (payload && payload.event) || {};
    var message = (payload && payload.sourceMeetingMessage) || {};
    var summary = (payload && payload.operatorSummary) || {};
    if (!event.eventId) {
      node.appendChild(el("p", "empty-state", "Transcript-to-memory confirmations will appear here."));
      return;
    }
    var summaryLine = el("div", "filter-summary meeting-promotion-operator-summary");
    var reviewStatus = summary.reviewStatus || event.reviewStatus || "pending";
    var promotionState = summary.promotionState || event.promotionState || "review_pending";
    var reviewId = summary.reviewId || event.reviewId || "";
    state.firstReviewId = reviewId || state.firstReviewId;
    summaryLine.appendChild(el("span", "filter-summary-label", "Meeting memory"));
    appendBadge(summaryLine, summary.scope || event.scope || "workspace", "neutral");
    appendBadge(summaryLine, summary.memoryType || event.memoryType || "evidence", "neutral");
    appendBadge(summaryLine, payload.visibleInSearch ? "search visible" : "search pending", payload.visibleInSearch ? "good" : "warn");
    appendBadge(summaryLine, payload.visibleInReviewQueue ? "review visible" : "review check", payload.visibleInReviewQueue ? "good" : "warn");
    appendBadge(summaryLine, reviewStatus, reviewStateKind(reviewStatus));
    appendBadge(summaryLine, formatStatusText(promotionState), reviewStateKind(promotionState));
    appendBadge(summaryLine, summary.firewallDecision || "accepted", summary.firewallDecision === "quarantine_for_review" ? "warn" : "good");
    appendBadge(summaryLine, summary.rawPayloadExposed ? "payload exposure review" : "payload hidden", summary.rawPayloadExposed ? "warn" : "good");
    var decisionForm = pick("[data-console-review-decision]");
    if (decisionForm && reviewId && decisionForm.elements.reviewId) {
      decisionForm.elements.reviewId.value = reviewId;
    }
    var row = resultRow(
      "Meeting saved as memory",
      event.summary || message.safeSummary || "Meeting transcript message was promoted into hosted memory.",
      [
        { text: summary.scope || event.scope || "workspace", kind: "neutral" },
        { text: summary.memoryType || event.memoryType || "evidence", kind: "neutral" },
        { text: reviewStatus, kind: reviewStateKind(reviewStatus) },
        { text: formatStatusText(promotionState), kind: reviewStateKind(promotionState) },
        { text: event.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "memory " + shortId(event.eventId),
        "review " + shortId(reviewId),
        payload.visibleInSearch ? "search visible" : "search pending",
        payload.visibleInReviewQueue ? "review queue visible" : "review queue pending",
        "meeting " + shortId(summary.meetingMessageId || message.meetingMessageId),
        "promoted by " + (summary.promotedByAgentId || state.agentId),
        "source sender " + (summary.sourceSenderAgentId || message.senderAgentId || "unknown"),
      ]
    );
    appendCopyActions(row, [
      { label: "Copy memory id", copyLabel: "Memory id", value: event.eventId },
      { label: "Copy review id", copyLabel: "Review id", value: summary.reviewId || event.reviewId },
      { label: "Copy meeting message id", copyLabel: "Meeting message id", value: summary.meetingMessageId || message.meetingMessageId },
    ]);
    node.appendChild(summaryLine);
    node.appendChild(row);
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
    state.latestReceiptItems = items.slice(0, 6);
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
    state.latestAuditItems = items.slice().reverse().slice(0, 6);
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
    state.latestReviewItems = items.slice(0, 6);
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
    renderLongTermMemoryReviewSummary(node, summary.longTermMemoryReviews);
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
      var memory = item.memory || {};
      var metaItems = [
        "proposed by " + (item.proposedByAgentId || "unknown"),
        "review " + shortId(item.reviewId),
        "memory " + shortId(item.memoryEventId),
        memory.source ? "source " + memory.source : "",
        memory.scope ? "scope " + memory.scope : "",
        memory.actorAgentId ? "actor " + memory.actorAgentId : "",
        "risk " + String(item.riskScore || 0),
        threats.length ? "threats " + threats.slice(0, 3).join(", ") : "",
        item.createdAt || "",
      ];
      var row = resultRow(
        "Review " + shortId(item.reviewId),
        item.publicSafeSummary || "No public-safe summary returned.",
        [
          { text: item.status || "pending", kind: item.status === "promoted" ? "good" : (item.status === "quarantined" ? "warn" : "neutral") },
          { text: memory.memoryType || item.reviewType || "memory", kind: "neutral" },
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
      if (memory.source) {
        var sourceButton = el("button", "button compact", "Copy source");
        sourceButton.type = "button";
        sourceButton.addEventListener("click", function () {
          copySafeText(memory.source, "Source path");
        });
        actions.appendChild(sourceButton);
      }
      row.appendChild(actions);
      node.appendChild(row);
    });
  }

  function renderLongTermMemoryReviewSummary(parent, reviewSummary) {
    if (!reviewSummary) {
      return;
    }
    var line = el("div", "filter-summary long-term-review-summary");
    line.appendChild(el("span", "filter-summary-label", "Long-term reviews"));
    appendBadge(line, formatStatusText(reviewSummary.status), reviewSummary.allPromoted ? "good" : "warn");
    appendBadge(line, (reviewSummary.count || 0) + " source paths", reviewSummary.count ? "good" : "neutral");
    appendBadge(line, (reviewSummary.visibleRecordCount || 0) + " visible", reviewSummary.visibleRecordCount ? "warn" : "neutral");
    appendBadge(line, (reviewSummary.recordCount || 0) + " records", reviewSummary.recordCount ? "neutral" : "good");
    if (reviewSummary.duplicateRecordCount) {
      appendBadge(line, reviewSummary.duplicateRecordCount + " duplicate records", "warn");
    }
    appendBadge(line, (reviewSummary.actionableCount || 0) + " actionable", reviewSummary.actionableCount ? "warn" : "good");
    appendCountBadges(line, "Status", reviewSummary.statusCounts, ["pending", "quarantined", "promoted", "rejected"]);
    parent.appendChild(line);
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

  function syncScopeId(scope) {
    if (scope === "company") {
      return state.companyId || state.workspaceId;
    }
    if (scope === "project") {
      return state.projectId || state.workspaceId;
    }
    return state.workspaceId;
  }

  function setSyncDeviceFields(deviceId, authorityEpoch) {
    if (!deviceId) {
      return;
    }
    state.syncLatestDeviceId = deviceId;
    var deviceForm = pick("[data-console-sync-device]");
    var mutationForm = pick("[data-console-sync-mutation]");
    if (deviceForm && deviceForm.elements.deviceId) {
      deviceForm.elements.deviceId.value = deviceId;
    }
    if (mutationForm && mutationForm.elements.deviceId) {
      mutationForm.elements.deviceId.value = deviceId;
    }
    if (mutationForm && mutationForm.elements.deviceEpoch && authorityEpoch) {
      mutationForm.elements.deviceEpoch.value = String(authorityEpoch);
    }
  }

  function setSyncReadbackFields(receiptId, logicalMemoryId, serverSequence, revisionId) {
    var readbackForm = pick("[data-console-sync-readback]");
    var mutationForm = pick("[data-console-sync-mutation]");
    if (readbackForm) {
      if (receiptId && readbackForm.elements.receiptId) {
        readbackForm.elements.receiptId.value = receiptId;
      }
      if (logicalMemoryId && readbackForm.elements.logicalMemoryId) {
        readbackForm.elements.logicalMemoryId.value = logicalMemoryId;
      }
      if (serverSequence !== undefined && serverSequence !== null && readbackForm.elements.afterSequence) {
        readbackForm.elements.afterSequence.value = String(Math.max(0, Number(serverSequence || 0) - 1));
      }
    }
    if (revisionId && mutationForm && mutationForm.elements.parentRevisionId) {
      mutationForm.elements.parentRevisionId.value = revisionId;
    }
  }

  function renderSyncCapabilitySummary(payload) {
    var node = pick("[data-console-sync-capability-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var capabilities = (payload && payload.data) || (payload && payload.capabilities) || {};
    var policy = (payload && payload.policy) || capabilities.retention || {};
    state.syncCapabilityStatus = capabilities.status || policy.schemaVersion || "available";
    renderOperatorMetrics();
    renderOperatorDesk();
    var summaryLine = el("div", "filter-summary sync-capability-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Sync capability"));
    appendBadge(summaryLine, capabilities.status || "available", capabilities.status === "live" ? "good" : "neutral");
    appendBadge(summaryLine, capabilities.protocol || "distributed sync", "neutral");
    appendBadge(summaryLine, policy.hardForgetSupported || (capabilities.mutationContract && capabilities.mutationContract.hardForgetSupported) ? "hard forget supported" : "hard forget rejected", policy.hardForgetSupported ? "warn" : "good");
    appendBadge(summaryLine, policy.rawPrivatePayloadStored ? "payload storage review" : "private payload not stored", policy.rawPrivatePayloadStored ? "warn" : "good");
    appendBadge(summaryLine, capabilities.rawCredentialExposed ? "credential exposure review" : "credentials hidden", capabilities.rawCredentialExposed ? "warn" : "good");
    node.appendChild(summaryLine);
    var routes = capabilities.routes || {};
    var row = resultRow(
      "Distributed sync contract",
      "Offline-capable clients register devices, submit idempotent mutations, then read back receipts, changes, and heads.",
      [
        { text: capabilities.publicSafeOnly ? "public-safe only" : "public-safety review", kind: capabilities.publicSafeOnly ? "good" : "warn" },
        { text: capabilities.valuesRedacted || policy.valuesRedacted ? "redacted" : "redaction review", kind: capabilities.valuesRedacted || policy.valuesRedacted ? "good" : "warn" },
        { text: capabilities.checkpointContract && capabilities.checkpointContract.monotonicServerSequence ? "monotonic sequence" : "checkpoint review", kind: capabilities.checkpointContract && capabilities.checkpointContract.monotonicServerSequence ? "good" : "warn" },
      ],
      [
        routes.registerDevice || "/api/matm/sync/devices",
        routes.submitMutation || "/api/matm/sync/mutations",
        routes.lookupReceipt || "/api/matm/sync/receipts",
        routes.changes || "/api/matm/sync/changes",
        routes.heads || "/api/matm/sync/heads",
      ]
    );
    node.appendChild(row);
  }

  function renderSyncDeviceSummary(payload) {
    var node = pick("[data-console-sync-device-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var device = (payload && payload.device) || {};
    var summary = (payload && payload.operatorSummary) || {};
    if (!device.deviceId) {
      node.appendChild(el("p", "empty-state", "Device authority confirmations will appear here."));
      return;
    }
    state.syncDeviceStatus = device.status || summary.status || "";
    setSyncDeviceFields(device.deviceId, device.authorityEpoch || summary.authorityEpoch);
    renderOperatorMetrics();
    renderOperatorDesk();
    var summaryLine = el("div", "filter-summary sync-device-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Device authority"));
    appendBadge(summaryLine, summary.action || "register", "neutral");
    appendBadge(summaryLine, device.status || "active", device.status === "revoked" ? "warn" : "good");
    appendBadge(summaryLine, "epoch " + String(device.authorityEpoch || summary.authorityEpoch || 0), "neutral");
    appendBadge(summaryLine, payload.persisted ? "persisted" : "readback pending", payload.persisted ? "good" : "warn");
    appendBadge(summaryLine, summary.rawPayloadExposed ? "payload exposure review" : "payload hidden", summary.rawPayloadExposed ? "warn" : "good");
    node.appendChild(summaryLine);
    var row = resultRow(
      "Sync device " + (summary.action || "registered"),
      device.label || "Device authority is ready for idempotent sync mutations.",
      [
        { text: device.status || "active", kind: device.status === "revoked" ? "warn" : "good" },
        { text: "epoch " + String(device.authorityEpoch || 0), kind: "neutral" },
        { text: payload.deviceAuthorityPersisted ? "authority persisted" : "authority review", kind: payload.deviceAuthorityPersisted ? "good" : "warn" },
        { text: device.valuesRedacted || payload.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "device " + shortId(device.deviceId),
        "agent " + (device.agentId || "unknown"),
        device.createdAt || "",
      ]
    );
    appendCopyActions(row, [
      { label: "Copy device id", copyLabel: "Sync device id", value: device.deviceId },
    ]);
    node.appendChild(row);
  }

  function renderSyncMutationSummary(payload) {
    var node = pick("[data-console-sync-mutation-summary]");
    if (!node) {
      return;
    }
    clear(node);
    var receipt = (payload && payload.receipt) || {};
    var revision = (payload && payload.revision) || {};
    var confirmation = (payload && payload.confirmation) || {};
    var summary = (payload && payload.operatorSummary) || {};
    var receiptId = receipt.receiptId || "";
    var revisionId = revision.syncRevisionId || receipt.syncRevisionId || "";
    var logicalMemoryId = receipt.logicalMemoryId || revision.logicalMemoryId || "";
    var serverSequence = payload && payload.serverSequence !== undefined ? payload.serverSequence : receipt.serverSequence;
    state.syncLatestReceiptId = receiptId;
    state.syncLatestRevisionId = revisionId;
    state.syncLatestServerSequence = serverSequence;
    state.syncLatestMutationStatus = (payload && payload.status) || receipt.status || "unknown";
    state.syncLatestLogicalMemoryId = logicalMemoryId;
    setSyncReadbackFields(receiptId, logicalMemoryId, serverSequence, payload && payload.status === "applied" ? revisionId : "");
    renderOperatorMetrics();
    renderOperatorDesk();
    var status = state.syncLatestMutationStatus;
    var conflictCode = receipt.conflictCode || summary.conflictCode || "";
    var summaryLine = el("div", "filter-summary sync-mutation-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Sync mutation"));
    appendBadge(summaryLine, status, status === "applied" ? "good" : "warn");
    appendBadge(summaryLine, "sequence " + String(serverSequence || 0), "neutral");
    appendBadge(summaryLine, confirmation.persisted || (payload && payload.persisted) ? "readback confirmed" : "readback pending", confirmation.persisted || (payload && payload.persisted) ? "good" : "warn");
    appendBadge(summaryLine, confirmation.receiptVisible ? "receipt visible" : "receipt check", confirmation.receiptVisible ? "good" : "warn");
    appendBadge(summaryLine, confirmation.revisionVisibleInChanges ? "change visible" : "change check", confirmation.revisionVisibleInChanges ? "good" : "warn");
    appendBadge(summaryLine, confirmation.headVisible ? "head visible" : "head check", confirmation.headVisible ? "good" : "warn");
    if (conflictCode) {
      appendBadge(summaryLine, conflictCode, "warn");
    }
    node.appendChild(summaryLine);
    var row = resultRow(
      "Sync mutation " + status,
      revision.summary || "Mutation receipt recorded without exposing raw idempotency keys or private payloads.",
      [
        { text: revision.operation || "mutation", kind: "neutral" },
        { text: revision.memoryType || "memory", kind: "neutral" },
        { text: receipt.conflict || (payload && payload.conflict) ? "conflict" : "no conflict", kind: receipt.conflict || (payload && payload.conflict) ? "warn" : "good" },
        { text: receipt.idempotencyKeyExposed ? "idempotency exposed" : "idempotency hidden", kind: receipt.idempotencyKeyExposed ? "warn" : "good" },
        { text: receipt.valuesRedacted || payload.valuesRedacted ? "redacted" : "", kind: "good" },
      ],
      [
        "receipt " + shortId(receiptId),
        "revision " + shortId(revisionId),
        "logical " + (logicalMemoryId || "not set"),
        "head " + shortId((payload && payload.head && payload.head.headRevisionId) || ""),
        payload && payload.receiptQueryUrl ? "receipt query ready" : "",
        payload && payload.changesQueryUrl ? "changes query ready" : "",
        payload && payload.headsQueryUrl ? "heads query ready" : "",
      ]
    );
    appendCopyActions(row, [
      { label: "Copy receipt id", copyLabel: "Sync receipt id", value: receiptId },
      { label: "Copy revision id", copyLabel: "Sync revision id", value: revisionId },
      { label: "Copy receipt query", copyLabel: "Sync receipt query URL", value: payload && payload.receiptQueryUrl },
      { label: "Copy changes query", copyLabel: "Sync changes query URL", value: payload && payload.changesQueryUrl },
      { label: "Copy heads query", copyLabel: "Sync heads query URL", value: payload && payload.headsQueryUrl },
    ]);
    node.appendChild(row);
  }

  function syncRevisionRow(item) {
    var row = resultRow(
      "Revision " + shortId(item.syncRevisionId),
      item.summary || "Sync revision.",
      [
        { text: item.operation || "mutation", kind: "neutral" },
        { text: item.status || "status", kind: item.status === "applied" ? "good" : "warn" },
        { text: "seq " + String(item.serverSequence || 0), kind: "neutral" },
        { text: item.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "logical " + (item.logicalMemoryId || "not set"),
        "revision " + shortId(item.syncRevisionId),
        "parent " + shortId(item.parentRevisionId),
        "actor " + (item.actorAgentId || "unknown"),
        item.source ? "source " + item.source : "",
      ]
    );
    return appendCopyActions(row, [
      { label: "Copy revision id", copyLabel: "Sync revision id", value: item.syncRevisionId },
      { label: "Copy logical id", copyLabel: "Logical memory id", value: item.logicalMemoryId },
    ]);
  }

  function syncHeadRow(item) {
    var row = resultRow(
      "Head " + (item.logicalMemoryId || "logical memory"),
      "Current sync head for this logical memory id.",
      [
        { text: item.status || "active", kind: item.status === "active" ? "good" : "warn" },
        { text: "seq " + String(item.serverSequence || item.indexedThroughSequence || 0), kind: "neutral" },
        { text: item.rawPayloadExposed ? "payload exposed" : "payload hidden", kind: item.rawPayloadExposed ? "warn" : "good" },
      ],
      [
        "head " + shortId(item.headRevisionId),
        "logical " + (item.logicalMemoryId || "not set"),
        item.updatedAt || "",
      ]
    );
    return appendCopyActions(row, [
      { label: "Copy head revision", copyLabel: "Head revision id", value: item.headRevisionId },
      { label: "Copy logical id", copyLabel: "Logical memory id", value: item.logicalMemoryId },
    ]);
  }

  function renderSyncReadback(payload, kind) {
    var node = pick("[data-console-sync-readback-list]");
    if (!node) {
      return;
    }
    clear(node);
    var label = kind || "readback";
    var items = [];
    if (label === "receipt") {
      items = payload && payload.receipt ? [payload.receipt] : [];
    } else if (label === "changes") {
      items = (payload && payload.changes && payload.changes.items) || [];
    } else {
      items = (payload && payload.items) || [];
    }
    if (label === "heads") {
      state.syncHeadCount = payload && payload.count !== undefined ? payload.count : items.length;
    }
    state.syncLastReadbackKind = label;
    state.syncLastReadbackCount = items.length;
    renderOperatorMetrics();
    renderOperatorDesk();
    var summaryLine = el("div", "filter-summary sync-readback-operator-summary");
    summaryLine.appendChild(el("span", "filter-summary-label", "Sync " + label));
    appendBadge(summaryLine, items.length + " row(s)", items.length ? "good" : "neutral");
    appendBadge(summaryLine, payload && payload.valuesRedacted ? "redacted" : "redaction review", payload && payload.valuesRedacted ? "good" : "warn");
    appendBadge(summaryLine, payload && payload.rawCredentialExposed ? "credential exposure review" : "credentials hidden", payload && payload.rawCredentialExposed ? "warn" : "good");
    if (label === "changes" && payload && payload.changes) {
      appendBadge(summaryLine, "indexed " + String(payload.changes.indexedThroughSequence || 0), "neutral");
      appendBadge(summaryLine, payload.changes.hasMore ? "more changes" : "checkpoint complete", payload.changes.hasMore ? "warn" : "good");
    }
    node.appendChild(summaryLine);
    if (!items.length) {
      node.appendChild(el("p", "empty-state", "No sync " + label + " rows returned."));
      return;
    }
    items.forEach(function (item) {
      if (label === "receipt") {
        var receiptRow = resultRow(
          "Receipt " + (item.status || "recorded"),
          "Receipt confirms the idempotent sync mutation without exposing the raw key.",
          [
            { text: item.status || "recorded", kind: item.status === "applied" ? "good" : "warn" },
            { text: "seq " + String(item.serverSequence || 0), kind: "neutral" },
            { text: item.idempotencyKeyExposed ? "idempotency exposed" : "idempotency hidden", kind: item.idempotencyKeyExposed ? "warn" : "good" },
            { text: item.valuesRedacted ? "redacted" : "", kind: "good" },
          ],
          [
            "receipt " + shortId(item.receiptId),
            "revision " + shortId(item.syncRevisionId),
            "logical " + (item.logicalMemoryId || "not set"),
            item.conflictCode ? "code " + item.conflictCode : "",
          ]
        );
        appendCopyActions(receiptRow, [
          { label: "Copy receipt id", copyLabel: "Sync receipt id", value: item.receiptId },
          { label: "Copy revision id", copyLabel: "Sync revision id", value: item.syncRevisionId },
        ]);
        node.appendChild(receiptRow);
      } else if (label === "changes") {
        node.appendChild(syncRevisionRow(item));
      } else {
        node.appendChild(syncHeadRow(item));
      }
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

  function publicApi(path) {
    return fetch(path, {
      method: "GET",
      headers: {"Accept": "application/json"},
      cache: "no-store",
    }).then(function (response) {
      return response.json().then(function (payload) {
        if (!response.ok || payload.ok === false) {
          var detail = payload.error && payload.error.detail ? payload.error.detail : "Request failed.";
          throw new Error(detail);
        }
        return payload;
      });
    });
  }

  function apiAllowingStatuses(path, options, allowedStatuses) {
    options = options || {};
    allowedStatuses = allowedStatuses || [];
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
        if ((!response.ok || payload.ok === false) && allowedStatuses.indexOf(response.status) === -1) {
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
      filters.event_id = form.elements.eventId ? form.elements.eventId.value.trim() : "";
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

  function refreshLongTermMemoryHealth() {
    if (!state.workspaceId) {
      state.longTermMemoryHealth = null;
      renderOperatorMetrics();
      return Promise.resolve(null);
    }
    var qs = query({
      workspace_id: state.workspaceId,
      q: longTermMemoryTag,
      tag: longTermMemoryTag,
    });
    return api("/api/matm/search?" + qs).then(function (payload) {
      var summary = (payload && payload.operatorSummary) || {};
      state.longTermMemoryHealth = summary.longTermMemoryMigration || null;
      renderOperatorMetrics();
      return payload;
    });
  }

  function showHostedLongTermMemory() {
    if (!state.key || !state.workspaceId) {
      setStatus("Load workspace before searching hosted long-term memory.", true);
      return Promise.resolve(null);
    }
    var form = pick("[data-console-search]");
    var queryControl = formControl(form, "query");
    if (form) {
      if (queryControl) {
        queryControl.value = longTermMemoryTag;
      }
      ["scope", "memoryType", "reviewStatus", "promotionState", "actorAgentId", "eventId"].forEach(function (field) {
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
      var migration = payload && payload.operatorSummary && payload.operatorSummary.longTermMemoryMigration;
      var sourceDetail = migration ? ", " + (migration.sourcePathCount || 0) + " source path(s)" : "";
      setStatus("Hosted long-term memory search refreshed: " + count + " item(s)" + sourceDetail + ".", false);
      return payload;
    });
  }

  function refreshInbox(agentId, exactFilters) {
    var requestedAgent = agentId || state.agentId;
    var requestSeq = state.inboxRequestSeq += 1;
    var filters = exactFilters !== undefined ? exactFilters : inboxExactFilters();
    var params = {workspace_id: state.workspaceId, agent_id: requestedAgent};
    if (filters && filters.messageId) {
      params.message_id = filters.messageId;
    }
    if (filters && filters.notificationId) {
      params.notification_id = filters.notificationId;
    }
    if (filters && filters.limit) {
      params.limit = filters.limit;
    }
    var qs = query(params);
    return api("/api/matm/current-message?" + qs).then(function (payload) {
      if (requestSeq !== state.inboxRequestSeq) {
        return null;
      }
      var resolvedAgent = inboxAgentFromPayload(payload, requestedAgent);
      setInboxAgent(resolvedAgent);
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstNotificationId = first && first.notification ? first.notification.notificationId : "";
      state.visibleNotificationRecords = {};
      state.visibleNotificationIds = ((payload && payload.items) || []).map(function (item) {
        var notification = item.notification || {};
        var message = item.message || {};
        var delivery = item.delivery || {};
        var notificationId = notification.notificationId;
        if (notificationId) {
          state.visibleNotificationRecords[notificationId] = {
            notificationId: notificationId,
            messageId: message.messageId || "",
            messageType: delivery.messageType || (message.targetAgentId || notification.targetAgentId ? "targeted" : "broadcast"),
            safeSummary: message.safeSummary || "",
            ackAgentId: resolvedAgent,
          };
        }
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

  function refreshRoutingDecisions() {
    if (!state.workspaceId) {
      renderRoutingDecisions({items: [], operatorSummary: {count: 0}});
      return Promise.resolve({items: []});
    }
    var form = pick("[data-console-routing-decision]");
    var params = {workspace_id: state.workspaceId, limit: 25};
    if (form) {
      params.routed_agent_id = form.elements.routedAgentId ? form.elements.routedAgentId.value.trim() : "";
      params.destination_room_id = form.elements.destinationRoomId ? form.elements.destinationRoomId.value.trim() : "";
      params.lane = form.elements.lane ? form.elements.lane.value.trim() : "";
    }
    var qs = query(params);
    return api("/api/matm/routing-decisions?" + qs).then(function (payload) {
      render("[data-console-meeting-output]", payload);
      renderRoutingDecisions(payload);
      return payload;
    });
  }

  function promoteMeetingMessage(message) {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before saving meeting messages as memory."));
    }
    var meetingMessageId = message && message.meetingMessageId;
    if (!meetingMessageId) {
      return Promise.reject(new Error("Select a meeting message before saving it as memory."));
    }
    return api("/api/matm/meeting-messages/promote", {
      method: "POST",
      headers: {"Idempotency-Key": "console-meeting-promote-" + meetingMessageId + "-" + Date.now()},
      body: {
        workspaceId: state.workspaceId,
        meetingMessageId: meetingMessageId,
        promotedByAgentId: state.agentId,
        memoryType: "evidence",
        title: "Meeting evidence: " + shortId(meetingMessageId),
        tags: ["meeting-message", "dogfood", "coordination"],
      },
    })
      .then(function (payload) {
        render("[data-console-memory-output]", payload);
        renderMeetingPromotion(payload);
        return refreshMemory(message.safeSummary || "meeting-message").then(function () {
          return refreshReviewQueue("pending").then(function () {
            return payload;
          });
        });
      })
      .then(function (payload) {
        setStatus("Meeting message saved as hosted memory and queued for review decision.", false);
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

  function inboxExactFilters() {
    var form = pick("[data-console-inbox]");
    var messageControl = formControl(form, "messageId");
    var notificationControl = formControl(form, "notificationId");
    var limitControl = formControl(form, "limit");
    return {
      messageId: messageControl ? messageControl.value.trim() : "",
      notificationId: notificationControl ? notificationControl.value.trim() : "",
      limit: limitControl ? limitControl.value : "25",
    };
  }

  function setInboxExactFilters(messageId, notificationId) {
    var form = pick("[data-console-inbox]");
    var messageControl = formControl(form, "messageId");
    var notificationControl = formControl(form, "notificationId");
    if (messageControl) {
      messageControl.value = messageId || "";
    }
    if (notificationControl) {
      notificationControl.value = notificationId || "";
    }
  }

  function openInboxLane(agentId, label) {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before refreshing inbox lanes."));
    }
    setInboxAgent(agentId);
    setInboxExactFilters("", "");
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

  function refreshSyncCapabilities() {
    return publicApi("/api/matm/sync/capabilities").then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncCapabilitySummary(payload);
      return payload;
    });
  }

  function refreshSyncRetention() {
    if (!state.key || !state.workspaceId) {
      return refreshSyncCapabilities();
    }
    var qs = query({workspace_id: state.workspaceId});
    return api("/api/matm/sync/retention?" + qs).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncCapabilitySummary(payload);
      return payload;
    });
  }

  function syncDeviceOperation(operation) {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before changing sync device authority."));
    }
    var form = pick("[data-console-sync-device]");
    var agentId = form && form.elements.agentId ? form.elements.agentId.value.trim() : state.agentId;
    var deviceId = form && form.elements.deviceId ? form.elements.deviceId.value.trim() : "";
    var label = form && form.elements.label ? form.elements.label.value.trim() : "";
    if ((operation === "rotate" || operation === "revoke") && !deviceId) {
      return Promise.reject(new Error("Device id is required for rotate and revoke."));
    }
    var path = "/api/matm/sync/devices";
    if (operation === "rotate") {
      path = "/api/matm/sync/devices/rotate";
    } else if (operation === "revoke") {
      path = "/api/matm/sync/devices/revoke";
    }
    return api(path, {
      method: "POST",
      headers: {"Idempotency-Key": "console-sync-device-" + operation + "-" + (deviceId || agentId) + "-" + Date.now()},
      body: {
        workspaceId: state.workspaceId,
        agentId: agentId || state.agentId,
        deviceId: deviceId,
        label: label,
      },
    }).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncDeviceSummary(payload);
      return payload;
    });
  }

  function submitSyncMutation() {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before submitting sync mutations."));
    }
    var form = pick("[data-console-sync-mutation]");
    if (!form) {
      return Promise.reject(new Error("Sync mutation form is unavailable."));
    }
    var logicalMemoryId = form.elements.logicalMemoryId.value.trim();
    var deviceId = form.elements.deviceId.value.trim();
    if (!logicalMemoryId) {
      return Promise.reject(new Error("Logical memory id is required for sync mutations."));
    }
    if (!deviceId) {
      return Promise.reject(new Error("Device id is required for sync mutations."));
    }
    var scope = form.elements.scope.value;
    var body = {
      workspaceId: state.workspaceId,
      actorAgentId: form.elements.actorAgentId.value.trim() || state.agentId,
      deviceId: deviceId,
      deviceEpoch: Number(form.elements.deviceEpoch.value || 1),
      logicalMemoryId: logicalMemoryId,
      operation: form.elements.operation.value,
      parentRevisionId: form.elements.parentRevisionId.value.trim(),
      scope: scope,
      scopeId: syncScopeId(scope),
      memoryType: form.elements.memoryType.value,
      title: form.elements.title.value.trim(),
      summary: form.elements.summary.value.trim(),
      sourceRef: form.elements.sourceRef.value.trim() || "memoryendpoints://console/sync-workflow",
    };
    return apiAllowingStatuses("/api/matm/sync/mutations", {
      method: "POST",
      headers: {"Idempotency-Key": "console-sync-mutation-" + logicalMemoryId + "-" + Date.now()},
      body: body,
    }, [409]).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncMutationSummary(payload);
      return payload;
    });
  }

  function syncReadbackParams() {
    var form = pick("[data-console-sync-readback]");
    return {
      receiptId: form && form.elements.receiptId ? form.elements.receiptId.value.trim() : "",
      afterSequence: form && form.elements.afterSequence ? form.elements.afterSequence.value : "0",
      logicalMemoryId: form && form.elements.logicalMemoryId ? form.elements.logicalMemoryId.value.trim() : "",
      limit: form && form.elements.limit ? form.elements.limit.value : "25",
    };
  }

  function readSyncReceipt() {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before reading sync receipts."));
    }
    var params = syncReadbackParams();
    var receiptId = params.receiptId || state.syncLatestReceiptId;
    if (!receiptId) {
      return Promise.reject(new Error("Receipt id is required for sync receipt readback."));
    }
    var qs = query({workspace_id: state.workspaceId, receipt_id: receiptId});
    return api("/api/matm/sync/receipts?" + qs).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncReadback(payload, "receipt");
      return payload;
    });
  }

  function readSyncChanges() {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before reading sync changes."));
    }
    var params = syncReadbackParams();
    var qs = query({
      workspace_id: state.workspaceId,
      after_sequence: params.afterSequence || 0,
      limit: params.limit || 25,
      logical_memory_id: params.logicalMemoryId,
    });
    return api("/api/matm/sync/changes?" + qs).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncReadback(payload, "changes");
      return payload;
    });
  }

  function readSyncHeads() {
    if (!state.key || !state.workspaceId) {
      return Promise.reject(new Error("Load workspace before reading sync heads."));
    }
    var params = syncReadbackParams();
    var qs = query({workspace_id: state.workspaceId, logical_memory_id: params.logicalMemoryId});
    return api("/api/matm/sync/heads?" + qs).then(function (payload) {
      render("[data-console-sync-output]", payload);
      renderSyncReadback(payload, "heads");
      return payload;
    });
  }

  function reviewQueueFilters(status) {
    var form = pick("[data-console-review]");
    var params = {workspace_id: state.workspaceId, status: status || ""};
    if (form) {
      params.status = status !== undefined ? status : (form.elements.status ? form.elements.status.value : "");
      params.source_prefix = form.elements.sourcePrefix ? form.elements.sourcePrefix.value.trim() : "";
      params.tag = form.elements.tag ? form.elements.tag.value.trim() : "";
      params.memory_type = form.elements.memoryType ? form.elements.memoryType.value : "";
      params.actor_agent_id = form.elements.actorAgentId ? form.elements.actorAgentId.value.trim() : "";
    }
    return params;
  }

  function refreshReviewQueue(status) {
    var qs = query(reviewQueueFilters(status));
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

  function bootstrapRefresh(label, task) {
    return Promise.resolve()
      .then(task)
      .then(function () {
        return {label: label, ok: true};
      })
      .catch(function (error) {
        return {label: label, ok: false, error: error && error.message ? error.message : String(error || "failed")};
      });
  }

  function renderBootstrapRefreshStatus(results) {
    var failures = (results || []).filter(function (result) {
      return !result.ok;
    });
    var completed = (results || []).filter(function (result) {
      return result.ok;
    }).map(function (result) {
      return result.label;
    });
    if (failures.length) {
      if (!completed.length) {
        setStatus(
          "Workspace loaded; operator views need attention: " + failures.map(function (result) { return result.label; }).join(", ") + ".",
          true
        );
        return results;
      }
      setStatus(
        "Workspace loaded; refreshed " + completed.join(", ") + ". Check " + failures.map(function (result) { return result.label; }).join(", ") + ".",
        true
      );
      return results;
    }
    setStatus("Workspace loaded; operator views refreshed: " + completed.join(", ") + ".", false);
    return results;
  }

  function refreshInitialConsoleViews() {
    var meetingRefresh = function () {
      return refreshMeetingRooms().then(function () {
        return refreshMeetingMessages(state.selectedMeetingRoomId);
      });
    };
    return Promise.all([
      bootstrapRefresh("memory", function () { return refreshMemory("verification"); }),
      bootstrapRefresh("long-term health", refreshLongTermMemoryHealth),
      bootstrapRefresh("reviews", function () { return refreshReviewQueue("pending"); }),
      bootstrapRefresh("meetings", meetingRefresh),
      bootstrapRefresh("routing", refreshRoutingDecisions),
      bootstrapRefresh("inbox", function () { return refreshInbox(state.agentId); }),
      bootstrapRefresh("lanes", refreshLaneOverview),
      bootstrapRefresh("receipts", refreshReceipts),
      bootstrapRefresh("audit", refreshAudit),
      bootstrapRefresh("sync", refreshSyncRetention),
    ]).then(renderBootstrapRefreshStatus);
  }

  function runConsoleCommand(action, label) {
    if (!state.key || !state.workspaceId) {
      setStatus("Load workspace before using operator commands.", true);
      renderCommandBar();
      return Promise.resolve(null);
    }
    var workflow = {
      memory: "memory",
      "long-term": "memory",
      sync: "sync",
      meetings: "meetings",
      messages: "messages",
      receipts: "evidence",
      audit: "evidence",
    }[action] || "workspace";
    setWorkflowView(workflow, true);
    var task;
    if (action === "memory") {
      var commandSearchQuery = formControl(searchForm, "query");
      if (commandSearchQuery && !commandSearchQuery.value.trim()) {
        commandSearchQuery.value = "verification";
      }
      task = refreshMemory(commandSearchQuery ? commandSearchQuery.value : "verification")
        .then(function (payload) {
          setStatus("Verification memory refreshed from the command bar.", false);
          return payload;
        });
    } else if (action === "long-term") {
      task = showHostedLongTermMemory();
    } else if (action === "sync") {
      task = refreshSyncRetention()
        .then(function (payload) {
          setStatus("Sync capabilities refreshed from the command bar.", false);
          return payload;
        });
    } else if (action === "meetings") {
      task = refreshMeetingRooms()
        .then(function () { return refreshMeetingMessages(state.selectedMeetingRoomId); })
        .then(function (payload) {
          setStatus("Meeting rooms refreshed from the command bar.", false);
          return payload;
        });
    } else if (action === "messages") {
      task = refreshInbox(state.agentId)
        .then(function () { return refreshLaneOverview(); })
        .then(function (payload) {
          setStatus("Message lanes refreshed from the command bar.", false);
          return payload;
        });
    } else if (action === "receipts") {
      task = refreshReceipts().then(function (payload) {
        setStatus("Receipts refreshed from the command bar.", false);
        return payload;
      });
    } else if (action === "audit") {
      task = refreshAudit().then(function (payload) {
        setStatus("Audit refreshed from the command bar.", false);
        return payload;
      });
    } else {
      task = Promise.resolve(null);
    }
    return task.catch(function (error) {
      setStatus((label || "Command") + " failed: " + error.message, true);
      return null;
    });
  }

  var authForm = pick("[data-console-auth]");
  var debugToggle = pick("[data-console-debug-toggle]");
  setDebugJsonVisible(debugToggle ? debugToggle.checked : false);
  setWorkflowView(defaultWorkflowView, false);
  updateSurfaceBadge();
  renderOperatorMetrics();
  renderCommandBar();
  refreshRuntimeVersion();
  refreshSyncCapabilities().catch(function () {});
  if (debugToggle) {
    debugToggle.addEventListener("change", function () {
      setDebugJsonVisible(debugToggle.checked);
      setStatus(debugToggle.checked ? "Debug JSON visible." : "Operator view active.", false);
    });
  }

  Array.prototype.forEach.call(consoleRoot.querySelectorAll("[data-console-workflow-view]"), function (button) {
    button.addEventListener("click", function () {
      setWorkflowView(button.getAttribute("data-console-workflow-view") || "all", true);
    });
  });

  Array.prototype.forEach.call(consoleRoot.querySelectorAll(".console-nav a[href^='#']"), function (link) {
    link.addEventListener("click", function () {
      var view = workflowViewByHash[link.getAttribute("href") || ""];
      if (view) {
        setWorkflowView(view, false);
      }
    });
  });

  Array.prototype.forEach.call(consoleRoot.querySelectorAll("[data-console-command]"), function (button) {
    button.addEventListener("click", function () {
      runConsoleCommand(button.getAttribute("data-console-command") || "", button.textContent);
    });
  });

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
        .then(refreshInitialConsoleViews)
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
        .then(function (payload) {
          var eventId = payload.canonicalMemoryEventId || (payload.event && payload.event.eventId) || "";
          var searchForm = pick("[data-console-search]");
          if (eventId && searchForm) {
            var queryControl = formControl(searchForm, "query");
            if (queryControl) {
              queryControl.value = "";
            }
            if (searchForm.elements.eventId) {
              searchForm.elements.eventId.value = eventId;
            }
          }
          return refreshMemory(eventId ? "" : "verification");
        })
        .then(function () { return refreshReviewQueue(reviewForm ? reviewForm.elements.status.value : "pending"); })
        .then(function () { setStatus("Memory saved; search and review queue refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var searchForm = pick("[data-console-search]");
  if (searchForm) {
    searchForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var queryControl = formControl(searchForm, "query");
      refreshMemory(queryControl ? queryControl.value : "").catch(function (error) {
        setStatus(error.message, true);
      });
    });
  }

  var clearSearchFiltersButton = pick("[data-console-clear-search-filters]");
  if (clearSearchFiltersButton && searchForm) {
    clearSearchFiltersButton.addEventListener("click", function () {
      ["scope", "memoryType", "reviewStatus", "promotionState", "tag", "actorAgentId", "eventId"].forEach(function (field) {
        if (searchForm.elements[field]) {
          searchForm.elements[field].value = "";
        }
      });
      var queryControl = formControl(searchForm, "query");
      refreshMemory(queryControl ? queryControl.value : "")
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

  var refreshSyncCapabilitiesButton = pick("[data-console-refresh-sync-capabilities]");
  if (refreshSyncCapabilitiesButton) {
    refreshSyncCapabilitiesButton.addEventListener("click", function () {
      refreshSyncCapabilities()
        .then(function () { setStatus("Sync capabilities refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var refreshSyncRetentionButton = pick("[data-console-refresh-sync-retention]");
  if (refreshSyncRetentionButton) {
    refreshSyncRetentionButton.addEventListener("click", function () {
      refreshSyncRetention()
        .then(function () { setStatus(state.workspaceId ? "Sync retention refreshed." : "Public sync capabilities refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncDeviceForm = pick("[data-console-sync-device]");
  if (syncDeviceForm) {
    syncDeviceForm.addEventListener("submit", function (event) {
      event.preventDefault();
      syncDeviceOperation("register")
        .then(function () { setStatus("Sync device registered and read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncDeviceRotateButton = pick("[data-console-sync-device-rotate]");
  if (syncDeviceRotateButton) {
    syncDeviceRotateButton.addEventListener("click", function () {
      syncDeviceOperation("rotate")
        .then(function () { setStatus("Sync device authority rotated and read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncDeviceRevokeButton = pick("[data-console-sync-device-revoke]");
  if (syncDeviceRevokeButton) {
    syncDeviceRevokeButton.addEventListener("click", function () {
      syncDeviceOperation("revoke")
        .then(function () { setStatus("Sync device revoked and read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncMutationForm = pick("[data-console-sync-mutation]");
  if (syncMutationForm) {
    syncMutationForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitSyncMutation()
        .then(function () { return readSyncReceipt(); })
        .then(function () { return readSyncChanges(); })
        .then(function () { return readSyncHeads(); })
        .then(function () { setStatus("Sync mutation submitted and read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncReadReceiptButton = pick("[data-console-sync-read-receipt]");
  if (syncReadReceiptButton) {
    syncReadReceiptButton.addEventListener("click", function () {
      readSyncReceipt()
        .then(function () { setStatus("Sync receipt read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncReadChangesButton = pick("[data-console-sync-read-changes]");
  if (syncReadChangesButton) {
    syncReadChangesButton.addEventListener("click", function () {
      readSyncChanges()
        .then(function () { setStatus("Sync changes read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var syncReadHeadsButton = pick("[data-console-sync-read-heads]");
  if (syncReadHeadsButton) {
    syncReadHeadsButton.addEventListener("click", function () {
      readSyncHeads()
        .then(function () { setStatus("Sync heads read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
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
      clearMeetingRoomSelection();
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
      clearMeetingRoomSelection();
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
            setMeetingRoom(payload.room.roomId, payload.room);
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

  var routingDecisionForm = pick("[data-console-routing-decision]");
  if (routingDecisionForm) {
    routingDecisionForm.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before creating a routing decision.", true);
        return;
      }
      var sourceRoomId = routingDecisionForm.elements.sourceRoomId.value.trim() || state.selectedMeetingRoomId;
      var destinationRoomId = routingDecisionForm.elements.destinationRoomId.value.trim() || state.selectedMeetingRoomId;
      var evidence = routingDecisionForm.elements.expectedEvidence.value.split(/\r?\n|,/).map(function (item) {
        return item.trim();
      }).filter(Boolean);
      if (!sourceRoomId || !destinationRoomId) {
        setStatus("Source and destination room ids are required for routing decisions.", true);
        return;
      }
      if (!evidence.length) {
        setStatus("Expected evidence is required for routing decisions.", true);
        return;
      }
      api("/api/matm/routing-decisions", {
        method: "POST",
        headers: {"Idempotency-Key": "console-routing-" + sourceRoomId + "-" + destinationRoomId + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          sourceRoomId: sourceRoomId,
          destinationRoomId: destinationRoomId,
          coordinatorAgentId: routingDecisionForm.elements.coordinatorAgentId.value.trim() || state.agentId,
          routedAgentId: routingDecisionForm.elements.routedAgentId.value.trim(),
          lane: routingDecisionForm.elements.lane.value.trim(),
          specificGoal: routingDecisionForm.elements.specificGoal.value.trim(),
          expectedEvidence: evidence,
          nextAction: routingDecisionForm.elements.nextAction.value.trim(),
          supportPlan: routingDecisionForm.elements.supportPlan.value.trim(),
        },
      })
        .then(function (payload) {
          render("[data-console-meeting-output]", payload);
          renderRoutingDecision(payload);
          if (payload.destinationRoomId) {
            setMeetingRoom(payload.destinationRoomId, payload.destinationRoom || null);
          }
          return refreshRoutingDecisions().then(function () {
            return refreshMeetingMessages(payload.canonicalRoomId || sourceRoomId);
          });
        })
        .then(function () { setStatus("Routing decision created and read back.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var refreshRoutingButton = pick("[data-console-refresh-routing-decisions]");
  if (refreshRoutingButton) {
    refreshRoutingButton.addEventListener("click", function () {
      if (!state.key || !state.workspaceId) {
        setStatus("Load workspace before refreshing routing decisions.", true);
        return;
      }
      refreshRoutingDecisions()
        .then(function () { setStatus("Routing decisions refreshed.", false); })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var meetingMessageForm = pick("[data-console-meeting-message]");
  if (meetingMessageForm) {
    meetingMessageForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var roomControl = formControl(meetingMessageForm, "roomId");
      var senderControl = formControl(meetingMessageForm, "senderAgentId");
      var summaryControl = formControl(meetingMessageForm, "safeSummary");
      var roomId = (roomControl && roomControl.value ? roomControl.value.trim() : "") || state.selectedMeetingRoomId;
      if (!roomId) {
        setStatus("Meeting room id is required.", true);
        return;
      }
      var senderAgentId = senderControl && senderControl.value ? senderControl.value.trim() : "";
      var safeSummary = summaryControl && summaryControl.value ? summaryControl.value.trim() : "";
      if (!senderAgentId || !safeSummary) {
        setStatus("Sender agent and safe meeting note are required.", true);
        return;
      }
      setMeetingRoom(roomId, state.selectedMeetingRoom && state.selectedMeetingRoom.roomId === roomId ? state.selectedMeetingRoom : null);
      api("/api/matm/meeting-messages", {
        method: "POST",
        headers: {"Idempotency-Key": "console-meeting-" + roomId + "-" + Date.now()},
        body: {
          workspaceId: state.workspaceId,
          roomId: roomId,
          senderAgentId: senderAgentId,
          safeSummary: safeSummary,
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
          var exactFilters = {
            messageId: payload.messageId || (payload.message && payload.message.messageId) || "",
            notificationId: payload.notificationId || (payload.notification && payload.notification.notificationId) || "",
            limit: inboxExactFilters().limit,
          };
          setInboxExactFilters(exactFilters.messageId, exactFilters.notificationId);
          return refreshInbox(refreshedLane, exactFilters).then(function (inboxPayload) {
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
      refreshReviewQueue().catch(function (error) {
        setStatus(error.message, true);
      });
    });
  }

  var longTermReviewsButton = pick("[data-console-long-term-reviews]");
  if (longTermReviewsButton && reviewForm) {
    longTermReviewsButton.addEventListener("click", function () {
      reviewForm.elements.status.value = "";
      reviewForm.elements.sourcePrefix.value = longTermMemorySourcePrefix;
      reviewForm.elements.tag.value = longTermMemoryTag;
      reviewForm.elements.memoryType.value = "";
      reviewForm.elements.actorAgentId.value = "";
      refreshReviewQueue()
        .then(function (payload) {
          var summary = payload && payload.operatorSummary && payload.operatorSummary.longTermMemoryReviews;
          var count = summary ? summary.sourcePathCount : ((payload && payload.count) || 0);
          setStatus("Long-term review queue refreshed: " + count + " source path(s).", false);
        })
        .catch(function (error) { setStatus(error.message, true); });
    });
  }

  var clearReviewFiltersButton = pick("[data-console-clear-review-filters]");
  if (clearReviewFiltersButton && reviewForm) {
    clearReviewFiltersButton.addEventListener("click", function () {
      reviewForm.elements.status.value = "pending";
      ["sourcePrefix", "tag", "memoryType", "actorAgentId"].forEach(function (field) {
        if (reviewForm.elements[field]) {
          reviewForm.elements[field].value = "";
        }
      });
      refreshReviewQueue()
        .then(function () { setStatus("Review filters cleared.", false); })
        .catch(function (error) { setStatus(error.message, true); });
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
        .then(function () {
          var queryControl = formControl(searchForm, "query");
          return refreshMemory(queryControl ? queryControl.value : "");
        })
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
    var ackContext = state.visibleNotificationRecords[notificationId] || {};
    return api("/api/matm/notifications/ack", {
      method: "POST",
      headers: {"Idempotency-Key": "console-ack-" + notificationId + (idempotencySuffix || "")},
      body: {
        workspaceId: state.workspaceId,
        notificationId: notificationId,
        consumerAgentId: state.agentId,
        status: "read",
      },
    }).then(function (payload) {
      if (ackContext.messageType === "broadcast" && ackContext.messageId) {
        state.lastAckedBroadcast = {
          messageId: ackContext.messageId,
          safeSummary: ackContext.safeSummary || "",
          ackAgentId: ackContext.ackAgentId || state.agentId,
          notificationId: notificationId,
        };
      }
      return payload;
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
