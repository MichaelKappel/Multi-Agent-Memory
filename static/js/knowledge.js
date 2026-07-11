(function () {
  const app = document.querySelector("[data-knowledge-app]");
  if (!app) return;

  const authForm = app.querySelector("[data-knowledge-auth]");
  const searchForm = app.querySelector("[data-knowledge-search]");
  const refreshButton = app.querySelector("[data-knowledge-refresh]");
  const treeEl = app.querySelector("[data-knowledge-tree]");
  const articleEl = app.querySelector("[data-knowledge-article]");
  const resultsEl = app.querySelector("[data-knowledge-results]");
  const statusEl = app.querySelector("[data-knowledge-status]");
  const state = { workspaceId: "", workspaceKey: "" };

  function setStatus(message, kind) {
    statusEl.textContent = message || "";
    statusEl.dataset.status = kind || "";
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function appendText(parent, tag, text, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = text || "";
    parent.appendChild(el);
    return el;
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
        throw new Error(error.title || error.detail || response.statusText || "Request failed.");
      }
      return payload;
    });
  }

  function documentButton(document) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "knowledge-link";
    button.dataset.documentId = document.searchDocumentId || "";
    const title = appendText(button, "span", document.title || "Untitled", "knowledge-link-title");
    title.title = document.routeOrPath || "";
    if (document.description) appendText(button, "span", document.description, "knowledge-link-description");
    if ((document.taxonomyPathLabels || []).length) appendText(button, "span", document.taxonomyPathLabels.join(" | "), "knowledge-link-path");
    if ((document.keywords || []).length) appendText(button, "span", document.keywords.join(", "), "knowledge-link-keywords");
    appendText(button, "span", document.routeOrPath || document.sourceUri || "", "knowledge-link-path");
    if (document.excerpt) appendText(button, "span", document.excerpt, "knowledge-link-excerpt");
    button.addEventListener("click", function () {
      loadDocument(document.searchDocumentId);
    });
    return button;
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
      (level.categories || []).forEach(function (category) {
        const details = document.createElement("details");
        details.open = true;
        const summary = document.createElement("summary");
        summary.textContent = category.category + " (" + (category.documentCount || 0) + ")";
        details.appendChild(summary);
        (category.documents || []).forEach(function (document) {
          details.appendChild(documentButton(document));
        });
        section.appendChild(details);
      });
      treeEl.appendChild(section);
    });
  }

  function renderMarkdownish(text, parent) {
    String(text || "")
      .split(/\r?\n/)
      .forEach(function (line) {
        const trimmed = line.trim();
        if (!trimmed) {
          parent.appendChild(document.createElement("br"));
          return;
        }
        const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
        if (heading) {
          appendText(parent, "h" + Math.min(4, heading[1].length + 1), heading[2]);
          return;
        }
        if (/^[-*]\s+/.test(trimmed)) {
          appendText(parent, "p", "\u2022 " + trimmed.replace(/^[-*]\s+/, ""), "knowledge-bullet");
          return;
        }
        appendText(parent, "p", trimmed);
      });
  }

  function renderArticle(document) {
    clearNode(articleEl);
    if (!document) {
      appendText(articleEl, "p", "Page not found.", "empty-state");
      return;
    }
    appendText(articleEl, "h1", document.title || "Untitled");
    if (document.description) appendText(articleEl, "p", document.description, "knowledge-article-description");
    const meta = appendText(
      articleEl,
      "p",
      [document.scope, document.category, document.routeOrPath].filter(Boolean).join(" / "),
      "knowledge-article-meta"
    );
    meta.title = document.sourceUri || "";
    if ((document.taxonomyPathLabels || []).length) {
      appendText(articleEl, "p", document.taxonomyPathLabels.join(" | "), "knowledge-article-taxonomy");
    }
    if ((document.keywords || []).length) {
      appendText(articleEl, "p", document.keywords.join(", "), "knowledge-article-keywords");
    }
    const content = document.createElement("div");
    content.className = "knowledge-article-content";
    renderMarkdownish(document.searchableText || "", content);
    articleEl.appendChild(content);
  }

  function renderResults(items) {
    clearNode(resultsEl);
    if (!items.length) {
      appendText(resultsEl, "p", "No matching pages.", "empty-state");
      return;
    }
    items.forEach(function (item) {
      resultsEl.appendChild(documentButton(item));
    });
  }

  function loadTree() {
    setStatus("Loading wiki...", "loading");
    return api("/api/matm/knowledge-tree", {})
      .then(function (payload) {
        renderTree(payload.tree || {});
        setStatus("Wiki loaded.", "ok");
        return payload;
      })
      .catch(function (error) {
        clearNode(treeEl);
        appendText(treeEl, "p", error.message, "empty-state");
        setStatus(error.message, "error");
      });
  }

  function loadDocument(documentId) {
    if (!documentId) return;
    setStatus("Loading page...", "loading");
    api("/api/matm/knowledge-documents", { document_id: documentId, include_text: "1", limit: "1" })
      .then(function (payload) {
        renderArticle((payload.items || [])[0]);
        setStatus("Page loaded.", "ok");
      })
      .catch(function (error) {
        clearNode(articleEl);
        appendText(articleEl, "p", error.message, "empty-state");
        setStatus(error.message, "error");
      });
  }

  function runSearch() {
    const form = new FormData(searchForm);
    const params = {
      q: form.get("q") || "",
      scope: form.get("scope") || "",
      category: form.get("category") || "",
      limit: "50",
    };
    setStatus("Searching...", "loading");
    api("/api/matm/knowledge-documents", params)
      .then(function (payload) {
        renderResults(payload.items || []);
        setStatus("Search complete.", "ok");
      })
      .catch(function (error) {
        clearNode(resultsEl);
        appendText(resultsEl, "p", error.message, "empty-state");
        setStatus(error.message, "error");
      });
  }

  authForm.addEventListener("submit", function (event) {
    event.preventDefault();
    const form = new FormData(authForm);
    state.workspaceId = String(form.get("workspaceId") || "").trim();
    state.workspaceKey = String(form.get("workspaceKey") || "").trim();
    loadTree();
  });

  searchForm.addEventListener("submit", function (event) {
    event.preventDefault();
    runSearch();
  });

  refreshButton.addEventListener("click", function () {
    loadTree();
  });
})();
