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
      return payload;
    });
  }

  function refreshInbox(agentId) {
    var qs = query({workspace_id: state.workspaceId, agent_id: agentId || state.agentId});
    return api("/api/matm/current-message?" + qs).then(function (payload) {
      var first = payload.items && payload.items.length ? payload.items[0] : null;
      state.firstNotificationId = first && first.notification ? first.notification.notificationId : "";
      render("[data-console-inbox-output]", payload);
      return payload;
    });
  }

  function refreshReceipts() {
    var qs = query({workspace_id: state.workspaceId, consumer_agent_id: state.agentId});
    return api("/api/matm/receipts?" + qs).then(function (payload) {
      render("[data-console-receipts-output]", payload);
      return payload;
    });
  }

  function refreshAudit() {
    var qs = query({workspace_id: state.workspaceId, limit: "50"});
    return api("/api/matm/audit-log?" + qs).then(function (payload) {
      render("[data-console-audit-output]", payload);
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
        .then(function () { setStatus("Memory saved and search refreshed.", false); })
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
