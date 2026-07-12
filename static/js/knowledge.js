(function () {
  const app = document.querySelector("[data-knowledge-app]");
  if (!app) return;

  const authForm = app.querySelector("[data-knowledge-auth]");
  const searchForm = app.querySelector("[data-knowledge-search]");
  const refreshButton = app.querySelector("[data-knowledge-refresh]");
  const modeButtons = Array.from(app.querySelectorAll("[data-knowledge-mode]"));
  const privateEl = app.querySelector("[data-knowledge-private]");
  const layoutEl = app.querySelector(".knowledge-layout");
  const treeEl = app.querySelector("[data-knowledge-tree]");
  const articleEl = app.querySelector("[data-knowledge-article]");
  const resultsEl = app.querySelector("[data-knowledge-results]");
  const statusEl = app.querySelector("[data-knowledge-status]");
  const state = { workspaceId: "", workspaceKey: "", searchMode: "pages", initialRoute: app.dataset.initialRoute || "" };

  function isInternalKnowledgeRoute(value) {
    const route = String(value || "");
    return /^\/knowledge\/(company|workspace|project)\/(?:[a-z0-9]+(?:-[a-z0-9]+)*\/)*[a-z0-9]+(?:-[a-z0-9]+)*$/.test(route);
  }

  function setStatus(message, kind) {
    statusEl.textContent = message || "";
    statusEl.dataset.status = kind || "";
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function setActiveArticle(active) {
    layoutEl.classList.toggle("knowledge-layout-has-article", Boolean(active));
    if (!active) articleEl.removeAttribute("tabindex");
  }

  function setActiveResults(active) {
    layoutEl.classList.toggle("knowledge-layout-has-results", Boolean(active));
  }

  function revealArticle() {
    articleEl.setAttribute("tabindex", "-1");
    articleEl.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 780px)").matches) {
      articleEl.scrollIntoView({ block: "start" });
    }
  }

  function lockPrivateKnowledge(clearCredentials) {
    privateEl.hidden = true;
    setActiveArticle(false);
    setActiveResults(false);
    clearNode(treeEl);
    clearNode(articleEl);
    clearNode(resultsEl);
    appendText(articleEl, "p", "Select a page.", "empty-state");
    appendText(resultsEl, "p", "Search results will appear here.", "empty-state");
    if (clearCredentials) {
      state.workspaceId = "";
      state.workspaceKey = "";
    }
  }

  function appendText(parent, tag, text, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = text || "";
    parent.appendChild(el);
    return el;
  }

  function lifecycleSummary(parent, knowledgeDocument, detailed) {
    const status = knowledgeDocument.knowledgeStatus || "current";
    const authority = knowledgeDocument.authorityLevel || "reviewed";
    const wrapper = document.createElement(detailed ? "section" : "span");
    wrapper.className = detailed ? "knowledge-lifecycle" : "knowledge-link-lifecycle";
    wrapper.dataset.knowledgeStatus = status;
    appendText(wrapper, "strong", status, "knowledge-lifecycle-status");
    appendText(wrapper, "span", authority, "knowledge-lifecycle-authority");
    if (detailed && (knowledgeDocument.statusReason || knowledgeDocument.lifecycleWarning)) {
      appendText(wrapper, "p", knowledgeDocument.statusReason || knowledgeDocument.lifecycleWarning, "knowledge-lifecycle-reason");
    }
    const replacement = knowledgeDocument.supersededBy || {};
    if (detailed && replacement.searchDocumentId) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button knowledge-replacement";
      button.textContent = "Open current replacement";
      button.title = replacement.title || replacement.routeOrPath || "Current replacement";
      button.addEventListener("click", function () {
        loadDocument(replacement.searchDocumentId);
      });
      wrapper.appendChild(button);
    }
    parent.appendChild(wrapper);
  }

  function api(path, params) {
    if (!state.workspaceId || !state.workspaceKey) {
      return Promise.reject(new Error("Workspace and key are required."));
    }
    const query = new URLSearchParams(params || {});
    query.set("workspace_id", state.workspaceId);
    return fetch(path + "?" + query.toString(), {
      headers: {
        Accept: "application/json",
        Authorization: "Bearer " + state.workspaceKey,
      },
    }).then(async function (response) {
      const payload = await response.json().catch(function () {
        return { ok: false, error: { title: response.statusText } };
      });
      if (!response.ok || !payload.ok) {
        const error = payload.error || {};
        const requestError = new Error(error.title || error.detail || response.statusText || "Request failed.");
        requestError.status = response.status;
        throw requestError;
      }
      return payload;
    });
  }

  function documentButton(knowledgeDocument) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "knowledge-link";
    button.dataset.documentId = knowledgeDocument.searchDocumentId || "";
    const title = appendText(button, "span", knowledgeDocument.title || "Untitled", "knowledge-link-title");
    title.title = knowledgeDocument.routeOrPath || "";
    lifecycleSummary(button, knowledgeDocument, false);
    if (knowledgeDocument.description) appendText(button, "span", knowledgeDocument.description, "knowledge-link-description");
    if ((knowledgeDocument.taxonomyPathLabels || []).length) appendText(button, "span", knowledgeDocument.taxonomyPathLabels.join(" | "), "knowledge-link-path");
    if ((knowledgeDocument.keywords || []).length) appendText(button, "span", knowledgeDocument.keywords.join(", "), "knowledge-link-keywords");
    appendText(button, "span", knowledgeDocument.routeOrPath || knowledgeDocument.sourceUri || "", "knowledge-link-path");
    if (knowledgeDocument.excerpt) appendText(button, "span", knowledgeDocument.excerpt, "knowledge-link-excerpt");
    button.addEventListener("click", function () {
      loadDocument(knowledgeDocument.searchDocumentId);
    });
    return button;
  }

  function externalLinkResult(link, compact) {
    const item = document.createElement("article");
    item.className = "external-link-result";
    appendText(item, "span", link.siteName || link.host || "External site", "external-link-site");
    const anchor = document.createElement("a");
    anchor.className = "external-link-title";
    anchor.href = link.url || link.pageUrl || "#";
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer external";
    anchor.textContent = link.pageTitle || link.url || "Untitled link";
    item.appendChild(anchor);
    if (link.description) appendText(item, "p", link.description, "external-link-description");
    appendText(item, "span", link.url || "", "external-link-url");
    if ((link.keywords || []).length) appendText(item, "span", link.keywords.join(", "), "external-link-keywords");
    if (!compact) {
      (link.mentions || []).forEach(function (mention) {
        const context = document.createElement("div");
        context.className = "external-link-context";
        appendText(context, "strong", mention.knowledgeDocumentTitle || mention.relationshipType || "Reference");
        if (mention.contextDescription) appendText(context, "span", mention.contextDescription);
        if (mention.knowledgeDocumentRoute) appendText(context, "span", mention.knowledgeDocumentRoute, "external-link-url");
        item.appendChild(context);
      });
    }
    return item;
  }

  function taxonomyDetails(node, depth) {
    const details = document.createElement("details");
    details.className = "knowledge-taxonomy-node";
    const summary = document.createElement("summary");
    summary.textContent = (node.label || "Untitled") + " (" + (node.documentCount || 0) + ")";
    details.appendChild(summary);
    let rendered = false;

    function renderContents() {
      if (rendered) return;
      rendered = true;
      const contents = document.createElement("div");
      contents.className = "knowledge-taxonomy-contents";
      (node.children || []).forEach(function (child) {
        contents.appendChild(taxonomyDetails(child, depth + 1));
      });
      (node.documents || []).forEach(function (knowledgeDocument) {
        contents.appendChild(documentButton(knowledgeDocument));
      });
      details.appendChild(contents);
    }

    details.addEventListener("toggle", function () {
      if (details.open) renderContents();
    });
    return details;
  }

  function renderTree(tree) {
    clearNode(treeEl);
    const levels = (tree && tree.levels) || [];
    if (!levels.length) {
      appendText(treeEl, "p", "No knowledge documents have been indexed yet.", "empty-state");
      return;
    }
    levels.forEach(function (level) {
      const section = document.createElement("section");
      section.className = "knowledge-tree-level";
      appendText(section, "h2", (level.scope || "scope") + " / " + (level.scopeId || ""), "knowledge-tree-heading");
      const taxonomy = level.taxonomy || [];
      if (taxonomy.length) {
        taxonomy.forEach(function (node) {
          section.appendChild(taxonomyDetails(node, 0));
        });
      } else {
        (level.categories || []).forEach(function (category) {
          const details = document.createElement("details");
          const summary = document.createElement("summary");
          summary.textContent = category.category + " (" + (category.documentCount || 0) + ")";
          details.appendChild(summary);
          details.addEventListener("toggle", function () {
            if (!details.open || details.dataset.rendered) return;
            details.dataset.rendered = "true";
            (category.documents || []).forEach(function (knowledgeDocument) {
              details.appendChild(documentButton(knowledgeDocument));
            });
          });
          section.appendChild(details);
        });
      }
      treeEl.appendChild(section);
    });
  }

  function appendInline(parent, source) {
    const text = String(source || "");
    const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(((?:https?:\/\/|\/knowledge\/)[^)\s]+)\)|\*([^*]+)\*)/g;
    let cursor = 0;
    let match;
    while ((match = pattern.exec(text))) {
      if (match.index > cursor) parent.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      let element;
      if (match[2]) {
        element = document.createElement("strong");
        element.textContent = match[2];
      } else if (match[3]) {
        element = document.createElement("code");
        element.textContent = match[3];
      } else if (match[4] && match[5]) {
        const linkHref = match[5];
        element = document.createElement("a");
        element.textContent = match[4];
        element.href = linkHref;
        if (isInternalKnowledgeRoute(linkHref)) {
          element.dataset.knowledgeRoute = linkHref;
          element.addEventListener("click", function (event) {
            if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            loadDocumentByRoute(linkHref);
          });
        } else {
          element.target = "_blank";
          element.rel = "noopener noreferrer external";
        }
      } else {
        element = document.createElement("em");
        element.textContent = match[6] || "";
      }
      parent.appendChild(element);
      cursor = pattern.lastIndex;
    }
    if (cursor < text.length) parent.appendChild(document.createTextNode(text.slice(cursor)));
  }

  function markdownCells(line) {
    return line
      .trim()
      .replace(/^\|/, "")
      .replace(/\|$/, "")
      .split("|")
      .map(function (cell) {
        return cell.trim();
      });
  }

  function renderMarkdownish(text, parent) {
    const lines = String(text || "").split(/\r?\n/);
    let index = 0;
    while (index < lines.length) {
      const trimmed = lines[index].trim();
      if (!trimmed) {
        index += 1;
        continue;
      }
      const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
      if (heading) {
        const headingElement = document.createElement("h" + Math.min(5, heading[1].length + 1));
        appendInline(headingElement, heading[2]);
        parent.appendChild(headingElement);
        index += 1;
        continue;
      }
      if (/^\|/.test(trimmed) && index + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[index + 1].trim())) {
        const table = document.createElement("table");
        const head = document.createElement("thead");
        const headRow = document.createElement("tr");
        markdownCells(trimmed).forEach(function (cell) {
          const th = document.createElement("th");
          appendInline(th, cell);
          headRow.appendChild(th);
        });
        head.appendChild(headRow);
        table.appendChild(head);
        const body = document.createElement("tbody");
        index += 2;
        while (index < lines.length && /^\|/.test(lines[index].trim())) {
          const row = document.createElement("tr");
          markdownCells(lines[index]).forEach(function (cell) {
            const td = document.createElement("td");
            appendInline(td, cell);
            row.appendChild(td);
          });
          body.appendChild(row);
          index += 1;
        }
        table.appendChild(body);
        const wrapper = document.createElement("div");
        wrapper.className = "knowledge-table-wrap";
        wrapper.appendChild(table);
        parent.appendChild(wrapper);
        continue;
      }
      if (/^[-*]\s+/.test(trimmed)) {
        const list = document.createElement("ul");
        while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
          const item = document.createElement("li");
          appendInline(item, lines[index].trim().replace(/^[-*]\s+/, ""));
          list.appendChild(item);
          index += 1;
        }
        parent.appendChild(list);
        continue;
      }
      if (/^\d+\.\s+/.test(trimmed)) {
        const list = document.createElement("ol");
        while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
          const item = document.createElement("li");
          appendInline(item, lines[index].trim().replace(/^\d+\.\s+/, ""));
          list.appendChild(item);
          index += 1;
        }
        parent.appendChild(list);
        continue;
      }
      if (/^>\s?/.test(trimmed)) {
        const quote = document.createElement("blockquote");
        appendInline(quote, trimmed.replace(/^>\s?/, ""));
        parent.appendChild(quote);
        index += 1;
        continue;
      }
      const paragraph = document.createElement("p");
      appendInline(paragraph, trimmed);
      parent.appendChild(paragraph);
      index += 1;
    }
  }

  function renderArticle(knowledgeDocument) {
    clearNode(articleEl);
    if (!knowledgeDocument) {
      setActiveArticle(false);
      appendText(articleEl, "p", "Page not found.", "empty-state");
      return;
    }
    setActiveArticle(true);
    appendText(articleEl, "h1", knowledgeDocument.title || "Untitled");
    lifecycleSummary(articleEl, knowledgeDocument, true);
    if (knowledgeDocument.description) appendText(articleEl, "p", knowledgeDocument.description, "knowledge-article-description");
    const meta = appendText(
      articleEl,
      "p",
      [knowledgeDocument.scope, knowledgeDocument.category, knowledgeDocument.routeOrPath].filter(Boolean).join(" / "),
      "knowledge-article-meta"
    );
    meta.title = knowledgeDocument.sourceUri || "";
    if ((knowledgeDocument.taxonomyPathLabels || []).length) {
      appendText(articleEl, "p", knowledgeDocument.taxonomyPathLabels.join(" | "), "knowledge-article-taxonomy");
    }
    if ((knowledgeDocument.keywords || []).length) {
      appendText(articleEl, "p", knowledgeDocument.keywords.join(", "), "knowledge-article-keywords");
    }
    const content = document.createElement("div");
    content.className = "knowledge-article-content";
    renderMarkdownish(knowledgeDocument.searchableText || "", content);
    articleEl.appendChild(content);
  }

  function renderDocumentLinks(items) {
    if (!items.length) return;
    const section = document.createElement("section");
    section.className = "knowledge-article-links";
    appendText(section, "h2", "External references");
    items.forEach(function (item) {
      section.appendChild(externalLinkResult(item, true));
    });
    articleEl.appendChild(section);
  }

  function renderResults(items) {
    clearNode(resultsEl);
    setActiveResults(true);
    if (!items.length) {
      appendText(resultsEl, "p", "No matching pages.", "empty-state");
      return;
    }
    items.forEach(function (item) {
      resultsEl.appendChild(documentButton(item));
    });
  }

  function renderExternalResults(items) {
    clearNode(resultsEl);
    setActiveResults(true);
    if (!items.length) {
      appendText(resultsEl, "p", "No matching web links.", "empty-state");
      return;
    }
    items.forEach(function (item) {
      resultsEl.appendChild(externalLinkResult(item, false));
    });
  }

  function loadTree() {
    setStatus("Loading wiki...", "loading");
    return api("/api/matm/knowledge-tree", {})
      .then(function (payload) {
        renderTree(payload.tree || {});
        privateEl.hidden = false;
        setStatus("Wiki loaded.", "ok");
        return payload;
      })
      .catch(function (error) {
        lockPrivateKnowledge(true);
        setStatus(error.message, "error");
      });
  }

  function setKnowledgeLocation(routeOrPath) {
    if (!isInternalKnowledgeRoute(routeOrPath) || window.location.pathname === routeOrPath) return;
    window.history.pushState({}, "", routeOrPath);
  }

  function loadDocumentRequest(params, options) {
    const settings = options || {};
    setStatus("Loading page...", "loading");
    return api("/api/matm/knowledge-documents", Object.assign({ include_text: "1", limit: "1" }, params || {}))
      .then(function (payload) {
        const document = (payload.items || [])[0];
        if (!document) throw new Error("Page not found.");
        renderArticle(document);
        if (settings.updateLocation !== false) setKnowledgeLocation(document.routeOrPath || "");
        return api("/api/matm/external-links", { document_id: document.searchDocumentId, limit: "100" });
      })
      .then(function (payload) {
        renderDocumentLinks(payload.items || []);
        setStatus("Page loaded.", "ok");
        revealArticle();
      })
      .catch(function (error) {
        if (error.status === 401) lockPrivateKnowledge(true);
        clearNode(articleEl);
        if (!privateEl.hidden) {
          setActiveArticle(true);
          appendText(articleEl, "p", error.message, "empty-state");
        }
        setStatus(error.message, "error");
      });
  }

  function loadDocument(documentId, options) {
    if (!documentId) return Promise.resolve();
    return loadDocumentRequest({ document_id: documentId }, options);
  }

  function loadDocumentByRoute(routeOrPath, options) {
    if (!isInternalKnowledgeRoute(routeOrPath)) {
      setStatus("Unsupported wiki route.", "error");
      return Promise.resolve();
    }
    return loadDocumentRequest({ route_or_path: routeOrPath }, options);
  }

  function runSearch() {
    const form = new FormData(searchForm);
    const params = {
      q: form.get("q") || "",
      scope: form.get("scope") || "",
      category: form.get("category") || "",
      knowledge_status: form.get("knowledgeStatus") || "",
      authority_level: form.get("authorityLevel") || "",
      limit: "50",
    };
    setStatus("Searching...", "loading");
    const endpoint = state.searchMode === "web" ? "/api/matm/internet-search" : "/api/matm/knowledge-documents";
    api(endpoint, params)
      .then(function (payload) {
        if (state.searchMode === "web") renderExternalResults(payload.items || []);
        else renderResults(payload.items || []);
        setStatus("Search complete.", "ok");
      })
      .catch(function (error) {
        if (error.status === 401) lockPrivateKnowledge(true);
        clearNode(resultsEl);
        if (!privateEl.hidden) appendText(resultsEl, "p", error.message, "empty-state");
        setStatus(error.message, "error");
      });
  }

  authForm.addEventListener("submit", function (event) {
    event.preventDefault();
    const form = new FormData(authForm);
    state.workspaceId = String(form.get("workspaceId") || "").trim();
    state.workspaceKey = String(form.get("workspaceKey") || "").trim();
    authForm.elements.workspaceKey.value = "";
    lockPrivateKnowledge(false);
    loadTree().then(function (payload) {
      if (!payload) return;
      const initialRoute = state.initialRoute;
      state.initialRoute = "";
      if (isInternalKnowledgeRoute(initialRoute)) loadDocumentByRoute(initialRoute, { updateLocation: false });
    });
  });

  searchForm.addEventListener("submit", function (event) {
    event.preventDefault();
    runSearch();
  });

  refreshButton.addEventListener("click", function () {
    loadTree();
  });

  modeButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      state.searchMode = button.dataset.knowledgeMode || "pages";
      modeButtons.forEach(function (candidate) {
        candidate.setAttribute("aria-selected", candidate === button ? "true" : "false");
      });
      runSearch();
    });
  });

  window.addEventListener("popstate", function () {
    if (!state.workspaceId || !state.workspaceKey) return;
    const route = window.location.pathname;
    if (isInternalKnowledgeRoute(route)) {
      loadDocumentByRoute(route, { updateLocation: false });
      return;
    }
    if (route === "/knowledge") {
      clearNode(articleEl);
      setActiveArticle(false);
      appendText(articleEl, "p", "Select a page.", "empty-state");
      setStatus("Wiki loaded.", "ok");
    }
  });
})();
