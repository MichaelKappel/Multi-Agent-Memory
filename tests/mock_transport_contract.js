"use strict";

const fs = require("node:fs");
const vm = require("node:vm");

const source = fs.readFileSync(process.argv[2], "utf8");
const siteSource = process.argv[3] ? fs.readFileSync(process.argv[3], "utf8") : "";
const context = {
  URL,
  Promise,
  JSON,
  Error,
  globalThis: null,
  fetch: function () { throw new Error("mock transport attempted network access"); },
};
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: process.argv[2] });

async function main() {
  const transport = context.MemoryEndpointsMockTransport.create({agentId:"MemoryEndpoints-Frontend-Agent"});
  const version = await transport.request("/api/version", {method:"GET"});
  if (!version.mockData || version.storeBackend !== "mock-transport") throw new Error("mock runtime version contract failed");
  const introspection = await transport.request("/api/matm/me", {method:"GET"});
  const principal = introspection.principal || {};
  const permissions = principal.permissions || {};
  if (!introspection.mockData || principal.credentialType !== "agent_token") throw new Error("mock credential introspection contract failed");
  if (principal.agentId !== "MemoryEndpoints-Frontend-Agent" || !principal.agentIdentityId || !principal.credentialId) throw new Error("mock principal binding contract failed");
  if (!principal.grant || principal.grant.scopeType !== "workspace" || principal.grant.scopeId !== "mock-workspace-memoryendpoints-tour" || principal.grant.immutable !== true) throw new Error("mock immutable grant contract failed");
  if (!principal.resourceContext || principal.resourceContext.workspaceId !== principal.grant.scopeId || principal.resourceContext.projectId !== "mock-project-memoryendpoints") throw new Error("mock resource context contract failed");
  if (permissions.canRead !== true || permissions.canWrite !== true || permissions.canAccessWorkspaceOperations !== true) throw new Error("mock operational permissions contract failed");
  if (permissions.canApproveAgentAccess !== false || permissions.canIssueAgentInvites !== false || permissions.canListAgentTokens !== false || permissions.canRevokeAgentTokens !== false || permissions.canManageCompany !== false) throw new Error("mock management denial contract failed");
  if (principal.immutableScope !== undefined || principal.credentialType === "agent") throw new Error("mock introspection compatibility alias detected");
  if (introspection.valuesRedacted !== true || introspection.rawCredentialExposed !== false || introspection.rawPayloadExposed !== false || principal.valuesRedacted !== true || principal.rawCredentialExposed !== false || principal.rawPayloadExposed !== false) throw new Error("mock introspection redaction contract failed");
  const workspace = await transport.request("/api/matm/workspace", {method:"GET"});
  if (!workspace.mockData || !workspace.workspace || workspace.workspace.mockData !== true) throw new Error("workspace contract failed");
  if (!workspace.operatorSummary.storage || workspace.operatorSummary.storage.usedBytes <= 0 || workspace.workspace.plan !== "public-tour") throw new Error("workspace operator shape failed");

  const rooms = await transport.request("/api/matm/meeting-rooms?agent_id=MemoryEndpoints-Frontend-Agent", {method:"GET"});
  const routing = await transport.request("/api/matm/routing-decisions?routed_agent_id=MemoryEndpoints-Frontend-Agent&status=active", {method:"GET"});
  const inbox = await transport.request("/api/matm/current-message?agent_id=MemoryEndpoints-Frontend-Agent", {method:"GET"});
  const unrelatedInbox = await transport.request("/api/matm/current-message?agent_id=MemoryEndpoints-Backend-Agent", {method:"GET"});
  if (rooms.items.length < 4 || !routing.items.length || routing.items[0].destinationRoomId !== "mock-room-task") throw new Error("attention-first room contract failed");
  if (inbox.items.length < 2 || inbox.items[0].message.responseRequired !== false || inbox.items[1].message.responseRequired !== true) throw new Error("mixed-attention inbox contract failed");
  if (unrelatedInbox.count !== 0 || unrelatedInbox.unreadCount !== 0) throw new Error("agent inbox isolation contract failed");

  const before = await transport.request("/api/matm/search?q=memory", {method:"GET"});
  const created = await transport.request("/api/matm/memory-events/submit", {method:"POST",body:{title:"Contract test",summary:"Session local",scope:"workspace",tags:[]}});
  const after = await transport.request("/api/matm/search?q=memory", {method:"GET"});
  if (!created.persisted || after.count !== before.count + 1) throw new Error("stateful mutation failed");

  transport.reset();
  const reset = await transport.request("/api/matm/search?q=memory", {method:"GET"});
  if (reset.count !== before.count) throw new Error("deterministic reset failed");

  for (const path of ["/api/matm/workspace-extra", "/api/matm/not-implemented"]) {
    let rejected = false;
    try {
      await transport.request(path, {method:"GET"});
    } catch (error) {
      rejected = error && error.code === "mock_operation_not_supported" && error.safeNoOp === true;
    }
    if (!rejected) throw new Error("unknown operation did not fail closed: " + path);
  }

  const missingResourceRequests = [
    ["/api/matm/meeting-messages?room_id=mock-room-missing", {method:"GET"}],
    ["/api/matm/meeting-messages", {method:"POST",body:{roomId:"mock-room-missing",safeSummary:"Should reject"}}],
    ["/api/matm/review-queue/decide", {method:"POST",body:{reviewId:"mock-review-missing",decision:"promote"}}],
    ["/api/matm/notifications/ack", {method:"POST",body:{notificationId:"mock-notification-missing"}}],
  ];
  for (const [path, options] of missingResourceRequests) {
    let rejected = false;
    try {
      await transport.request(path, options);
    } catch (error) {
      rejected = error && error.code === "mock_resource_not_found" && error.safeNoOp === true;
    }
    if (!rejected) throw new Error("unknown mock resource did not fail closed: " + path);
  }

  if (siteSource) {
    const start = siteSource.indexOf("function refreshRuntimeVersion");
    const end = siteSource.indexOf("function countMeta", start);
    const runtimeBlock = siteSource.slice(start, end);
    if (!runtimeBlock.includes('publicApi("/api/version")') || runtimeBlock.includes('fetch("/api/version"')) {
      throw new Error("demo runtime version is not routed through the mock-aware public API helper");
    }
  }
  process.stdout.write(JSON.stringify({ok:true,networkCalls:0,mockIntrospection:true,agentManagementDenied:true,unknownOperationsRejected:true,unknownResourcesRejected:true,agentInboxIsolation:true,demoRuntimeNetworkCalls:0,deterministicReset:true}));
}

main().catch(function (error) {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
