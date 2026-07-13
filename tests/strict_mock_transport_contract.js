"use strict";

const fs = require("node:fs");
const vm = require("node:vm");

const sourcePath = process.argv[2];
if (!sourcePath) {
  throw new Error("Usage: node tests/strict_mock_transport_contract.js static/js/mock-transport.js");
}

let networkCalls = 0;
const source = fs.readFileSync(sourcePath, "utf8");
const context = {
  URL,
  Promise,
  JSON,
  Error,
  globalThis: null,
  fetch() {
    networkCalls += 1;
    throw new Error("mock transport attempted network access");
  },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: sourcePath });

const failures = [];

function requireContract(condition, message) {
  if (!condition) throw new Error(message);
}

async function check(name, operation) {
  try {
    await operation();
  } catch (error) {
    failures.push({ check: name, detail: error && error.message ? error.message : String(error) });
  }
}

async function safeRejection(transport, path, options, allowedCodes) {
  let error = null;
  try {
    await Promise.resolve().then(() => transport.request(path, options || {}));
  } catch (caught) {
    error = caught;
  }
  requireContract(error, "request unexpectedly succeeded");
  requireContract(allowedCodes.includes(error.code), "unexpected error code " + String(error.code));
  requireContract(error.safeNoOp === true, "safeNoOp must be true");
  requireContract(error.valuesRedacted === true, "valuesRedacted must be true");
  requireContract(error.rawCredentialExposed === false, "rawCredentialExposed must be false");
  requireContract(error.rawPayloadExposed === false, "rawPayloadExposed must be false");
}

async function main() {
  const create = context.MemoryEndpointsMockTransport && context.MemoryEndpointsMockTransport.create;
  requireContract(typeof create === "function", "mock transport factory is unavailable");
  const transport = create({ agentId: "MemoryEndpoints-Frontend-Agent" });

  await check("canonical agent-token introspection", async () => {
    const payload = await transport.request("/api/matm/me", { method: "GET" });
    const principal = payload.principal || {};
    const permissions = principal.permissions || {};
    requireContract(payload.mockData === true, "introspection is not labeled mock data");
    requireContract(principal.credentialType === "agent_token", "credential type is not canonical");
    requireContract(principal.agentId === "MemoryEndpoints-Frontend-Agent", "agent identity is not transport-bound");
    requireContract(principal.grant && principal.grant.scopeType === "workspace" && principal.grant.scopeId === "mock-workspace-memoryendpoints-tour" && principal.grant.immutable === true, "immutable workspace grant is incomplete");
    requireContract(principal.resourceContext && principal.resourceContext.workspaceId === principal.grant.scopeId && principal.resourceContext.projectId === "mock-project-memoryendpoints", "resource context is incomplete");
    requireContract(permissions.canRead === true && permissions.canWrite === true && permissions.canAccessWorkspaceOperations === true, "operational permissions are incomplete");
    requireContract(permissions.canApproveAgentAccess === false && permissions.canIssueAgentInvites === false && permissions.canListAgentTokens === false && permissions.canRevokeAgentTokens === false && permissions.canManageCompany === false, "agent management permission was granted");
    requireContract(principal.immutableScope === undefined, "compatibility alias is present");
    requireContract(payload.valuesRedacted === true && payload.rawCredentialExposed === false && payload.rawPayloadExposed === false, "top-level redaction flags are incomplete");
    requireContract(principal.valuesRedacted === true && principal.rawCredentialExposed === false && principal.rawPayloadExposed === false, "principal redaction flags are incomplete");
  });

  await check("exact method and path rejection", async () => {
    const cases = [
      ["/api/matm/workspace/", { method: "GET" }],
      ["/api/matm/workspace", { method: "POST" }],
      ["/api/matm/x/../workspace", { method: "GET" }],
      ["https://attacker.invalid/api/matm/workspace", { method: "GET" }],
    ];
    for (const [path, options] of cases) {
      await safeRejection(transport, path, options, ["mock_operation_not_supported", "mock_invalid_request"]);
    }
  });

  await check("typed malformed request rejection", async () => {
    for (const path of ["http://[", "https://%", { unexpected: true }]) {
      await safeRejection(transport, path, { method: "GET" }, ["mock_invalid_request"]);
    }
  });

  await check("memory search filters", async () => {
    const noMatch = await transport.request("/api/matm/search?q=no-such-memory", { method: "GET" });
    const company = await transport.request("/api/matm/search?scope=company", { method: "GET" });
    const decision = await transport.request("/api/matm/search?memory_type=decision", { method: "GET" });
    requireContract(noMatch.count === 0, "q filter did not narrow search");
    requireContract(company.items.length > 0 && company.items.every((item) => item.scope === "company"), "scope filter did not narrow search");
    requireContract(decision.items.length > 0 && decision.items.every((item) => item.memoryType === "decision"), "memory_type filter did not narrow search");
    requireContract(noMatch.filters && company.filters && decision.filters, "search response omitted effective filters");
  });

  await check("knowledge adapter and filters", async () => {
    const exact = await transport.request("/api/matm/knowledge-documents", {
      document_id: "mock-knowledge-overview",
      include_text: "1",
      limit: "1",
    });
    const company = await transport.request("/api/matm/knowledge-documents?scope=company", { method: "GET" });
    const archived = await transport.request("/api/matm/knowledge-documents?knowledge_status=archived", { method: "GET" });
    requireContract(exact.count === 1 && exact.items[0].searchDocumentId === "mock-knowledge-overview", "knowledge adapter parameters were dropped");
    requireContract(company.items.length > 0 && company.items.every((item) => item.scope === "company"), "knowledge scope filter did not narrow results");
    requireContract(archived.count === 0, "knowledge lifecycle filter did not narrow results");
    requireContract(company.filters && archived.filters, "knowledge response omitted effective filters");
  });

  await check("meeting receipt and audit filters", async () => {
    const taskRooms = await transport.request("/api/matm/meeting-rooms?scope=task", { method: "GET" });
    const receipts = await transport.request("/api/matm/receipts?consumer_agent_id=no-such-agent", { method: "GET" });
    const audit = await transport.request("/api/matm/audit-log?action=no-such-action", { method: "GET" });
    requireContract(taskRooms.items.length > 0 && taskRooms.items.every((item) => item.scope === "task"), "room scope filter did not narrow results");
    requireContract(receipts.count === 0, "receipt consumer filter did not narrow results");
    requireContract(audit.count === 0, "audit action filter did not narrow results");
    requireContract(taskRooms.filters && receipts.filters && audit.filters, "filtered response omitted effective filters");
  });

  await check("unknown routing and device resources", async () => {
    const requests = [
      ["/api/matm/routing-decisions", { method: "POST", body: { sourceRoomId: "mock-room-missing", destinationRoomId: "mock-room-task", routedAgentId: "agent" } }],
      ["/api/matm/sync/devices/rotate", { method: "POST", body: { deviceId: "mock-device-missing" } }],
      ["/api/matm/sync/devices/revoke", { method: "POST", body: { deviceId: "mock-device-missing" } }],
      ["/api/matm/sync/mutations", { method: "POST", body: { deviceId: "mock-device-missing", logicalMemoryId: "mock-logical" } }],
    ];
    for (const [path, options] of requests) {
      await safeRejection(transport, path, options, ["mock_resource_not_found"]);
    }
  });

  await check("workspace search and retention schema parity", async () => {
    const workspace = await transport.request("/api/matm/workspace", { method: "GET" });
    const search = await transport.request("/api/matm/search?q=memory", { method: "GET" });
    const retention = await transport.request("/api/matm/sync/retention", { method: "GET" });
    requireContract(workspace.valuesRedacted === true && workspace.rawCredentialExposed === false && workspace.rawPayloadExposed === false, "workspace response omitted top-level redaction flags");
    requireContract(typeof workspace.workspace.storageLimitBytes === "number", "workspace storageLimitBytes is missing");
    requireContract(search.memorySource && search.filesystemDocsIncluded === false && search.filters, "search source/filter schema is incomplete");
    requireContract(search.valuesRedacted === true && search.rawCredentialExposed === false && search.rawPayloadExposed === false, "search response omitted top-level redaction flags");
    requireContract(retention.policy && retention.capabilities && !retention.retention, "retention response must use policy and capabilities");
    requireContract(retention.valuesRedacted === true && retention.rawCredentialExposed === false && retention.rawPayloadExposed === false, "retention response omitted redaction flags");
  });

  await check("deterministic reset and session isolation", async () => {
    const resetTransport = create({ agentId: "MemoryEndpoints-Frontend-Agent" });
    const pristine = resetTransport.snapshot();
    const other = create({ agentId: "MemoryEndpoints-Frontend-Agent" });
    await resetTransport.request("/api/matm/memory-events/submit", { method: "POST", body: { title: "Session A", summary: "Local", scope: "workspace" } });
    const changed = await resetTransport.request("/api/matm/search", { method: "GET" });
    const untouched = await other.request("/api/matm/search", { method: "GET" });
    requireContract(changed.count === untouched.count + 1, "state leaked across transport instances");
    resetTransport.reset();
    requireContract(JSON.stringify(resetTransport.snapshot()) === JSON.stringify(pristine), "reset did not restore the pristine repository");
  });

  if (networkCalls !== 0) failures.push({ check: "zero network", detail: "fetch was called " + networkCalls + " times" });
  const report = { ok: failures.length === 0, failureCount: failures.length, failures, networkCalls };
  process.stdout.write(JSON.stringify(report));
  if (failures.length) process.exitCode = 1;
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, failureCount: 1, failures: [{ check: "verifier", detail: error.message }], networkCalls }));
  process.exitCode = 1;
});
