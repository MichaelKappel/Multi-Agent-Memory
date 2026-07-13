(function (root) {
  "use strict";

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function createRepository() {
    var workspace = {
      workspaceId: "mock-workspace-memoryendpoints-tour",
      companyId: "mock-company-endpoint-ecosystem",
      accountId: "mock-account-public-demo",
      primaryProjectId: "mock-project-memoryendpoints",
      label: "MemoryEndpoints Product Tour (Mock)",
      companyLabel: "Endpoint Ecosystem (Mock)",
      projectLabel: "MemoryEndpoints.com (Mock)",
      plan: "public-tour",
      status: "active",
      quotaBytes: 209715200,
      storageLimitBytes: 209715200,
      usedBytes: 1843200,
      remainingBytes: 207872000,
      storageUsedBytes: 1843200,
      storageRemainingBytes: 207872000,
      quotaExceeded: false,
      rawKeyStoredByServer: false,
      accounts: [{accountId:"mock-account-public-demo",label:"Public Tour Account (Mock)",role:"owner",status:"active"}],
      company: {companyId:"mock-company-endpoint-ecosystem",label:"Endpoint Ecosystem (Mock)",status:"active"},
      projects: [{projectId:"mock-project-memoryendpoints",label:"MemoryEndpoints.com (Mock)",status:"active"}],
      valuesRedacted: true,
      rawCredentialExposed: false,
      rawPayloadExposed: false,
      mockData: true
    };
    var memories = [
      {eventId:"mock-mem-interface",scope:"project",title:"One interface, two transports (Mock)",summary:"The product tour and authenticated workspace use the same forms, workflows, and renderers. Only the data transport is overloaded.",memoryType:"decision",reviewStatus:"promoted",promotionState:"promoted",actorAgentId:"MemoryEndpoints-Frontend-Agent",tags:["mock-data","architecture"]},
      {eventId:"mock-mem-boundary",scope:"workspace",title:"Local and hosted memory boundary (Mock)",summary:"Local .uai files preserve startup continuity. MemoryEndpoints adds protected search, review, meetings, messages, receipts, audit, and durable wiki knowledge.",memoryType:"procedure",reviewStatus:"promoted",promotionState:"promoted",actorAgentId:"MemoryEndpoints-Backend-Agent",tags:["mock-data","uaix"]},
      {eventId:"mock-mem-ecosystem",scope:"company",title:"Endpoint ecosystem map (Mock)",summary:"LocalEndpoints.com covers local endpoint boundaries, UAIX.org supplies portable guidance, and LLMWikis.org explores knowledge interfaces.",memoryType:"fact",reviewStatus:"promoted",promotionState:"promoted",actorAgentId:"MemoryEndpoints-Frontend-Agent",tags:["mock-data","ecosystem"]}
    ];
    var documents = [
      {searchDocumentId:"mock-knowledge-overview",title:"How MemoryEndpoints works (Mock)",scope:"project",scopeId:"mock-project-memoryendpoints",category:"architecture",routeOrPath:"/tour/knowledge/project/memoryendpoints/how-it-works",knowledgeStatus:"current",authorityLevel:"canonical",description:"A crawler-friendly tour of the product boundary using clearly labeled mock records.",taxonomyPathLabels:["MemoryEndpoints","Architecture","System tour"],keywords:["mock data","MATM","memory","coordination"],searchableText:"# One interface, two transports\nThe authenticated experience uses a workspace bearer key and protected MATM routes. The public tour uses a session-local transport, while the wiki components, search, filters, navigation, and renderers remain the same.\n\n## Durable workflow\n1. Save public-safe memory.\n2. Review and promote it.\n3. Coordinate in meeting rooms and current-message lanes.\n4. Confirm delivery with redacted receipts and audit evidence.\n\n> Every record on this tour is mock data and nothing is persisted."},
      {searchDocumentId:"mock-knowledge-boundaries",title:"Memory boundaries and privacy (Mock)",scope:"workspace",scopeId:"mock-workspace-memoryendpoints-tour",category:"governance",routeOrPath:"/tour/knowledge/workspace/demo/memory-boundaries",knowledgeStatus:"current",authorityLevel:"reviewed",description:"Why local startup memory and protected durable memory are additive.",taxonomyPathLabels:["MemoryEndpoints","Governance","Privacy"],keywords:["UAIX","redaction","workspace key"],searchableText:"# Memory boundaries\nLocal `.uai` files provide cold-start continuity for filesystem agents. MemoryEndpoints provides protected, searchable mid-to-long-term memory. Neither silently replaces the other.\n\n- Workspace keys remain session-local.\n- Raw private payloads stay out of receipts.\n- Tour mode never calls protected routes.\n- Knowledge belongs to company, workspace, or project scopes."},
      {searchDocumentId:"mock-knowledge-ecosystem",title:"Endpoint ecosystem guide (Mock)",scope:"company",scopeId:"mock-company-endpoint-ecosystem",category:"ecosystem",routeOrPath:"/tour/knowledge/company/endpoint-ecosystem/product-map",knowledgeStatus:"current",authorityLevel:"reference",description:"The distinct roles of MemoryEndpoints and neighboring projects.",taxonomyPathLabels:["Ecosystem","Products","Responsibilities"],keywords:["LocalEndpoints","UAIX","LLMWikis"],searchableText:"# Related systems\n- [LocalEndpoints.com](https://localendpoints.com) focuses on local endpoint boundaries.\n- [UAIX.org](https://uaix.org) provides portable AI and agent guidance.\n- [LLMWikis.org](https://llmwikis.org) explores knowledge interfaces.\n\nMemoryEndpoints.com owns the protected MATM memory, wiki, meeting, messaging, receipt, and audit experience shown here."}
    ];
    var links = [
      {externalLinkId:"mock-link-local",siteName:"LocalEndpoints.com",host:"localendpoints.com",pageTitle:"LocalEndpoints.com",url:"https://localendpoints.com",description:"Related local endpoint project (Mock citation).",keywords:["local endpoints","execution"]},
      {externalLinkId:"mock-link-uaix",siteName:"UAIX.org",host:"uaix.org",pageTitle:"UAIX",url:"https://uaix.org",description:"Portable AI and agent guidance (Mock citation).",keywords:["UAIX","agent guidance"]},
      {externalLinkId:"mock-link-wikis",siteName:"LLMWikis.org",host:"llmwikis.org",pageTitle:"LLMWikis.org",url:"https://llmwikis.org",description:"Related knowledge-interface project (Mock citation).",keywords:["wiki","knowledge"]}
    ];
    var companyRoom = {roomId:"mock-room-company",name:"Endpoint Ecosystem Welcome Room (Mock)",scope:"company",scopeId:workspace.companyId,purpose:"New agents identify themselves here before routing into narrower work.",unreadCount:3,messageCount:8,lastMessageAt:"Demo sequence 03",alwaysAvailable:true};
    var assignedRoom = {roomId:"mock-room-task",name:"Public UI Review Task (Mock)",scope:"task",scopeId:"mock-task-public-ui",purpose:"Frontend and backend agents review the public experience through the real task-room interface.",unreadCount:2,messageCount:5,lastMessageAt:"Demo sequence 04",alwaysAvailable:true};
    var projectRoom = {roomId:"mock-room-project",name:"MemoryEndpoints Product Room (Mock)",scope:"project",scopeId:workspace.primaryProjectId,purpose:"Project-wide implementation decisions and evidence stay discoverable here.",unreadCount:0,messageCount:12,lastMessageAt:"Demo sequence 02",alwaysAvailable:true};
    var workspaceRoom = {roomId:"mock-room-workspace",name:"Agent Operations Workspace Room (Mock)",scope:"workspace",scopeId:workspace.workspaceId,purpose:"Shared operating context for authorized agents in this workspace.",unreadCount:0,messageCount:0,alwaysAvailable:true};
    return {
      workspace: workspace,
      memories: memories,
      documents: documents,
      links: links,
      rooms: [companyRoom, assignedRoom, projectRoom, workspaceRoom],
      meetingMessages: [{meetingMessageId:"mock-meeting-message",roomId:assignedRoom.roomId,scope:"task",senderAgentId:"MemoryEndpoints-Backend-Agent",safeSummary:"Backend contract confirmed: a tour may overload data transport, never product workflows. (Mock)",createdAt:"Demo sequence 04",valuesRedacted:true,rawPayloadExposed:false}],
      notifications: [
        {notificationId:"mock-notification-ack",messageId:"mock-current-message-ack",senderAgentId:"swarm-observer-agent",targetAgentId:"MemoryEndpoints-Frontend-Agent",safeSummary:"The mock knowledge and receipt surfaces are ready for inspection. (Mock)",responseRequired:false,responseDisposition:"viewed_acknowledgement",read:false,createdAt:"Demo sequence 02"},
        {notificationId:"mock-notification",messageId:"mock-current-message",senderAgentId:"MemoryEndpoints-Backend-Agent",targetAgentId:"MemoryEndpoints-Frontend-Agent",safeSummary:"Review the mock workspace, memory, wiki, meeting, and receipt surfaces through the real operator controls. (Mock)",responseRequired:true,responseDisposition:"required_response",read:false,createdAt:"Demo sequence 03"}
      ],
      receipts: [{receiptId:"mock-receipt",notificationId:"mock-notification",status:"read",consumerAgentId:"MemoryEndpoints-Frontend-Agent",valuesRedacted:true,rawPayloadExposed:false,createdAt:"Demo session"}],
      routingDecisions: [{routingDecisionId:"mock-routing",routedAgentId:"MemoryEndpoints-Frontend-Agent",destinationRoomId:assignedRoom.roomId,lane:"public-tour-review",specificGoal:"Review the public product tour through the real operator UI. (Mock)",nextAction:"Open the assigned task room, then inspect memory, knowledge, meetings, messages, receipts, and audit evidence.",status:"active",createdAt:"Demo sequence 04",valuesRedacted:true}],
      syncRevisions: [],
      syncReceipt: null,
      syncDevice: null
    };
  }

  function safeError(code) {
    var error = new Error("The mock request was safely rejected.");
    error.code = code;
    error.safeNoOp = true;
    error.valuesRedacted = true;
    error.rawCredentialExposed = false;
    error.rawPayloadExposed = false;
    return error;
  }

  function requestKey(path, options) {
    if (typeof path !== "string" || typeof options !== "object" || options === null || Array.isArray(options)) {
      throw safeError("mock_invalid_request");
    }
    if (path.charAt(0) !== "/" || path.charAt(1) === "/" || path.indexOf("\\") !== -1 || path.indexOf("#") !== -1) {
      throw safeError("mock_invalid_request");
    }
    var rawPath = path.split("?")[0];
    var rawSegments = rawPath.split("/");
    for (var segmentIndex = 0; segmentIndex < rawSegments.length; segmentIndex += 1) {
      var decodedSegment;
      try {
        decodedSegment = decodeURIComponent(rawSegments[segmentIndex]);
      } catch (_decodeError) {
        throw safeError("mock_invalid_request");
      }
      if (decodedSegment === "." || decodedSegment === ".." || decodedSegment.indexOf("/") !== -1 || decodedSegment.indexOf("\\") !== -1) {
        throw safeError("mock_invalid_request");
      }
    }
    var parsed;
    try {
      parsed = new URL(path, "https://memoryendpoints.invalid");
    } catch (_urlError) {
      throw safeError("mock_invalid_request");
    }
    if (parsed.origin !== "https://memoryendpoints.invalid" || parsed.pathname !== rawPath) {
      throw safeError("mock_invalid_request");
    }
    var rawMethod = options.method === undefined ? "GET" : options.method;
    if (typeof rawMethod !== "string" || !/^[A-Za-z]+$/.test(rawMethod)) {
      throw safeError("mock_invalid_request");
    }
    var method = rawMethod.toUpperCase();
    var query = new URL("https://memoryendpoints.invalid/?" + parsed.searchParams.toString()).searchParams;
    if (method === "GET") {
      var reserved = {method:true,headers:true,body:true,credentials:true,cache:true,signal:true,mode:true,redirect:true,referrer:true,referrerPolicy:true,integrity:true,keepalive:true};
      Object.keys(options).forEach(function (name) {
        if (reserved[name] || options[name] === undefined || options[name] === null) return;
        var value = options[name];
        if (typeof value !== "string" && typeof value !== "number" && typeof value !== "boolean") {
          throw safeError("mock_invalid_request");
        }
        query.set(name, String(value));
      });
    }
    return {key:method+" "+parsed.pathname,method:method,pathname:parsed.pathname,query:query};
  }

  function queryValue(query, names) {
    for (var index = 0; index < names.length; index += 1) {
      var value = query.get(names[index]);
      if (value !== null && value !== "") return value;
    }
    return "";
  }

  function compactFilters(filters) {
    var active = {};
    Object.keys(filters).forEach(function (key) {
      if (filters[key] !== undefined && filters[key] !== null && filters[key] !== "") active[key] = filters[key];
    });
    return active;
  }

  function requestedLimit(query, fallback) {
    var parsed = parseInt(query.get("limit") || String(fallback), 10);
    if (!isFinite(parsed) || parsed < 1) return fallback;
    return Math.min(parsed, 100);
  }

  function countBy(items, property, fallback) {
    var counts = {};
    items.forEach(function (item) {
      var value = item[property] || fallback;
      counts[value] = (counts[value] || 0) + 1;
    });
    return counts;
  }

  function create(options) {
    options = options || {};
    var repository = createRepository();
    var agentId = options.agentId || "MemoryEndpoints-Frontend-Agent";

    function rejectUnknown(key) {
      return Promise.reject(safeError("mock_operation_not_supported"));
    }

    function resourceFailure(resourceType, resourceId) {
      return {
        __mockReject: true,
        code: "mock_resource_not_found",
        resourceType: resourceType,
      };
    }

    function response(descriptor, requestOptions) {
      var key = descriptor.key;
      var query = descriptor.query;
      var body = (requestOptions && requestOptions.body) || {};
      var workspace = repository.workspace;
      var memories = repository.memories;

      if (key === "GET /api/version") return {ok:true,version:"public-tour",storeBackend:"mock-transport",storeBackendStatus:"session-local",storeBackendVerified:true,build:{sourceShaShort:"mock-tour",sourceWorktreeDirty:false},valuesRedacted:true,mockData:true};
      if (key === "GET /api/matm/me") return {
        ok: true,
        principal: {
          credentialId: "mock-credential-frontend-agent",
          credentialType: "agent_token",
          companyId: workspace.companyId,
          agentId: agentId,
          agentIdentityId: "mock-agent-identity-frontend",
          displayName: "MemoryEndpoints Frontend Agent (Mock)",
          grant: {
            scopeType: "workspace",
            scopeId: workspace.workspaceId,
            accessRule: "scope_and_descendants",
            immutable: true,
            supersedesCredentialId: null,
            memoryTransferFromCredentialId: null
          },
          permissions: {
            canRead: true,
            canWrite: true,
            canApproveAgentAccess: false,
            canIssueAgentInvites: false,
            canListAgentTokens: false,
            canRevokeAgentTokens: false,
            canManageCompany: false,
            canAccessWorkspaceOperations: true
          },
          resourceContext: {
            workspaceId: workspace.workspaceId,
            projectId: workspace.primaryProjectId
          },
          valuesRedacted: true,
          rawCredentialExposed: false,
          rawPayloadExposed: false
        },
        valuesRedacted: true,
        rawCredentialExposed: false,
        rawPayloadExposed: false,
        mockData: true
      };
      if (key === "GET /api/matm/workspace") return {ok:true,workspace:clone(workspace),operatorSummary:{hierarchyReady:true,hierarchy:[{level:"account",id:workspace.accountId,label:"Public Tour Account (Mock)",role:"owner",status:"active"},{level:"company",id:workspace.companyId,label:workspace.companyLabel,status:"active"},{level:"workspace",id:workspace.workspaceId,label:workspace.label,plan:workspace.plan,status:"active"},{level:"project",id:workspace.primaryProjectId,label:workspace.projectLabel,status:"active"}],storage:{quotaBytes:workspace.quotaBytes,usedBytes:workspace.usedBytes,remainingBytes:workspace.remainingBytes,quotaExceeded:false},privacy:{rawKeyStoredByServer:false,rawCredentialExposed:false,rawPayloadExposed:false},storageBackend:"mock-transport",valuesRedacted:true},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      if (key === "POST /api/matm/agents/register") return {ok:true,agent:{agentId:body.agentId || agentId,displayName:"Public Tour Operator (Mock)"},operatorSummary:{registered:true},mockData:true};
      if (key === "GET /api/matm/search" || key === "GET /api/matm/memory-events") {
        var memoryFilters = {
          scope: queryValue(query, ["scope"]),
          scopeId: queryValue(query, ["scope_id", "scopeId"]),
          memoryType: queryValue(query, ["memory_type", "memoryType", "type"]),
          reviewStatus: queryValue(query, ["review_status", "reviewStatus", "status"]),
          promotionState: queryValue(query, ["promotion_state", "promotionState"]),
          sourcePrefix: queryValue(query, ["source_prefix", "sourcePrefix"]),
          tag: queryValue(query, ["tag"]),
          actorAgentId: queryValue(query, ["actor_agent_id", "actorAgentId"]),
          eventId: queryValue(query, ["event_id", "eventId", "memory_event_id", "memoryEventId"])
        };
        var activeMemoryFilters = compactFilters(memoryFilters);
        var memoryQuery = queryValue(query, ["q", "query"]).toLowerCase();
        var matchedMemories = memories.filter(function (item) {
          if (memoryQuery && JSON.stringify(item).toLowerCase().indexOf(memoryQuery) === -1) return false;
          if (memoryFilters.scope && item.scope !== memoryFilters.scope) return false;
          if (memoryFilters.scopeId && item.scopeId !== memoryFilters.scopeId) return false;
          if (memoryFilters.memoryType && item.memoryType !== memoryFilters.memoryType) return false;
          if (memoryFilters.reviewStatus && item.reviewStatus !== memoryFilters.reviewStatus) return false;
          if (memoryFilters.promotionState && item.promotionState !== memoryFilters.promotionState) return false;
          if (memoryFilters.sourcePrefix && String(item.sourceRef || "").indexOf(memoryFilters.sourcePrefix) !== 0) return false;
          if (memoryFilters.tag && (item.tags || []).indexOf(memoryFilters.tag) === -1) return false;
          if (memoryFilters.actorAgentId && item.actorAgentId !== memoryFilters.actorAgentId) return false;
          if (memoryFilters.eventId && item.eventId !== memoryFilters.eventId) return false;
          return true;
        }).slice(0, requestedLimit(query, 50));
        var memorySummary = {count:matchedMemories.length,hostedMemoryCount:matchedMemories.length,query:memoryQuery,filters:activeMemoryFilters,scopeCounts:countBy(matchedMemories,"scope","unknown"),reviewStatusCounts:countBy(matchedMemories,"reviewStatus","unknown"),promotionStateCounts:countBy(matchedMemories,"promotionState","unknown"),memorySource:"hosted_workspace_store",filesystemDocsIncluded:false,filesystemIncluded:false,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
        return {ok:true,items:clone(matchedMemories),memories:clone(matchedMemories),count:matchedMemories.length,memorySource:"hosted_workspace_store",filesystemDocsIncluded:false,filters:activeMemoryFilters,operatorSummary:memorySummary,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "POST /api/matm/memory-events/submit") {
        var memoryId="mock-mem-created-"+(memories.length+1);
        var memory={eventId:memoryId,scope:body.scope||"workspace",scopeId:body.scopeId||workspace.workspaceId,title:(body.title||"Untitled")+" (Mock)",summary:(body.summary||"")+" (Mock data; session-local.)",memoryType:body.memoryType||"status",reviewStatus:"pending",promotionState:"review_pending",actorAgentId:body.actorAgentId||agentId,tags:(body.tags||[]).concat(["mock-data"]),firewall:{decision:"accepted"}};
        memories.unshift(memory);
        return {ok:true,event:clone(memory),canonicalMemoryEventId:memoryId,persisted:true,visibleInSearch:true,visibleInReviewQueue:true,operatorSummary:{memoryEventId:memoryId,scope:memory.scope,memoryType:memory.memoryType,reviewStatus:"pending",firewallDecision:"accepted",rawPayloadExposed:false,rawCredentialExposed:false},mockData:true};
      }
      if (key === "GET /api/matm/review-queue") {
        var reviews=memories.map(function(item){return {reviewId:"mock-review-"+item.eventId,memoryEventId:item.eventId,status:item.reviewStatus||"pending",proposedByAgentId:item.actorAgentId,publicSafeSummary:item.summary,firewallDecision:"accepted",riskScore:0,detectedThreats:[],valuesRedacted:true,memory:clone(item)};});
        var reviewCounts={pending:0,quarantined:0,promoted:0,rejected:0}; reviews.forEach(function(item){reviewCounts[item.status]=(reviewCounts[item.status]||0)+1;});
        return {ok:true,items:reviews,count:reviews.length,operatorSummary:{count:reviews.length,statusCounts:reviewCounts,firewallDecisionCounts:{accepted:reviews.length,quarantine_for_review:0},detectedThreatCount:0},mockData:true};
      }
      if (key === "POST /api/matm/review-queue/decide") {
        var reviewed=memories.filter(function(item){return "mock-review-"+item.eventId===body.reviewId;})[0];
        if(!reviewed)return resourceFailure("review",body.reviewId);
        var status=body.decision==="promote"?"promoted":body.decision;
        reviewed.reviewStatus=status;reviewed.promotionState=status;
        return {ok:true,review:{reviewId:body.reviewId,memoryEventId:reviewed.eventId,status:status,reviewerAgentId:body.reviewerAgentId,valuesRedacted:true,rawPayloadExposed:false,updatedAt:"Demo session"},operatorSummary:{reviewId:body.reviewId,memoryEventId:reviewed.eventId,status:status,reviewerAgentId:body.reviewerAgentId,statusCounts:{promoted:status==="promoted"?1:0,rejected:status==="rejected"?1:0,quarantined:status==="quarantined"?1:0},valuesRedacted:true,reviewNoteExposed:false,rawPayloadExposed:false,rawCredentialExposed:false},mockData:true};
      }
      if (key === "GET /api/matm/meeting-rooms") {
        var roomFilters = compactFilters({
          agentId: queryValue(query, ["agent_id", "agentId"]),
          scope: queryValue(query, ["scope"]).toLowerCase(),
          scopeId: queryValue(query, ["scope_id", "scopeId"])
        });
        var matchedRooms = repository.rooms.filter(function (item) {
          if (roomFilters.scope && item.scope !== roomFilters.scope) return false;
          if (roomFilters.scopeId && item.scopeId !== roomFilters.scopeId) return false;
          return true;
        });
        var roomSummary = {count:matchedRooms.length,filters:roomFilters,unreadCount:matchedRooms.reduce(function(total,item){return total+(item.unreadCount||0);},0),alwaysAvailableCount:matchedRooms.filter(function(item){return item.alwaysAvailable;}).length,scopeCounts:countBy(matchedRooms,"scope","unknown"),valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
        return {ok:true,schemaVersion:"memoryendpoints.meeting_rooms.v1",items:clone(matchedRooms),count:matchedRooms.length,filters:roomFilters,operatorSummary:roomSummary,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "POST /api/matm/meeting-rooms") { var newRoom={roomId:"mock-room-created-"+(repository.rooms.length+1),name:(body.name||"Tour room")+" (Mock)",scope:body.scope||"goal",scopeId:body.scopeId||"mock-goal",purpose:body.purpose||"Session-local mock room.",unreadCount:0,messageCount:0,lastMessageAt:"",alwaysAvailable:true}; repository.rooms.push(newRoom); return {ok:true,room:clone(newRoom),persisted:true,visibleToSender:true,operatorSummary:{roomId:newRoom.roomId,scope:newRoom.scope,rawPayloadExposed:false},mockData:true}; }
      if (key === "GET /api/matm/meeting-messages") { var requestedRoomId=query.get("room_id")||query.get("roomId")||""; var requestedRoom=repository.rooms.filter(function(item){return item.roomId===requestedRoomId;})[0]; if(!requestedRoom)return resourceFailure("meeting room",requestedRoomId); var roomMessages=repository.meetingMessages.filter(function(item){return item.roomId===requestedRoom.roomId;}); return {ok:true,room:clone(requestedRoom),items:clone(roomMessages),count:roomMessages.length,visibleMessageCount:roomMessages.length,totalMessageCount:roomMessages.length,operatorSummary:{visibleMessageCount:roomMessages.length,totalMessageCount:roomMessages.length,unreadCount:requestedRoom.unreadCount||0,senderAgentCounts:{"MemoryEndpoints-Frontend-Agent":roomMessages.filter(function(item){return item.senderAgentId==="MemoryEndpoints-Frontend-Agent";}).length,"MemoryEndpoints-Backend-Agent":roomMessages.filter(function(item){return item.senderAgentId==="MemoryEndpoints-Backend-Agent";}).length}},mockData:true}; }
      if (key === "POST /api/matm/meeting-messages") { var messageRoom=repository.rooms.filter(function(item){return item.roomId===body.roomId;})[0]; if(!messageRoom)return resourceFailure("meeting room",body.roomId); var meeting={meetingMessageId:"mock-meeting-created-"+(repository.meetingMessages.length+1),roomId:messageRoom.roomId,scope:messageRoom.scope,senderAgentId:body.senderAgentId||agentId,safeSummary:(body.safeSummary||"")+" (Mock)",createdAt:"Demo session",valuesRedacted:true,rawPayloadExposed:false}; repository.meetingMessages.push(meeting); messageRoom.messageCount=(messageRoom.messageCount||0)+1; messageRoom.lastMessageAt="Demo sequence created"; return {ok:true,message:clone(meeting),meetingMessage:clone(meeting),persisted:true,visibleToSender:true,visibleInTranscript:true,operatorSummary:{meetingMessageId:meeting.meetingMessageId,roomId:meeting.roomId,valuesRedacted:true,rawPayloadExposed:false,rawCredentialExposed:false},mockData:true}; }
      if (key === "POST /api/matm/meeting-messages/promote") { var promotedMeeting=repository.meetingMessages.filter(function(item){return item.meetingMessageId===body.meetingMessageId;})[0]; if(!promotedMeeting)return resourceFailure("meeting message",body.meetingMessageId); return {ok:true,event:clone(memories[0]),persisted:true,visibleInSearch:true,operatorSummary:{memoryEventId:memories[0].eventId,rawPayloadExposed:false},mockData:true}; }
      if (key === "POST /api/matm/meeting-rooms/read") { var readRoom=repository.rooms.filter(function(item){return item.roomId===body.roomId;})[0]; if(!readRoom)return resourceFailure("meeting room",body.roomId); readRoom.unreadCount=0; return {ok:true,roomId:body.roomId,agentId:body.agentId||agentId,updated:true,operatorSummary:{unreadCount:0},mockData:true}; }
      if (key === "GET /api/matm/routing-decisions") {
        var routingFilters = compactFilters({
          roomId: queryValue(query, ["room_id", "roomId", "source_room_id", "sourceRoomId"]),
          destinationRoomId: queryValue(query, ["destination_room_id", "destinationRoomId"]),
          routedAgentId: queryValue(query, ["routed_agent_id", "routedAgentId"]),
          coordinatorAgentId: queryValue(query, ["coordinator_agent_id", "coordinatorAgentId"]),
          lane: queryValue(query, ["lane"]),
          destinationScope: queryValue(query, ["destination_scope", "destinationScope"]),
          destinationScopeId: queryValue(query, ["destination_scope_id", "destinationScopeId"]),
          status: queryValue(query, ["status"])
        });
        var matchedDecisions = repository.routingDecisions.filter(function (item) {
          if (routingFilters.roomId && item.sourceRoomId !== routingFilters.roomId) return false;
          if (routingFilters.destinationRoomId && item.destinationRoomId !== routingFilters.destinationRoomId) return false;
          if (routingFilters.routedAgentId && item.routedAgentId !== routingFilters.routedAgentId) return false;
          if (routingFilters.coordinatorAgentId && item.coordinatorAgentId !== routingFilters.coordinatorAgentId) return false;
          if (routingFilters.lane && item.lane !== routingFilters.lane) return false;
          if (routingFilters.destinationScope && item.destinationScope !== routingFilters.destinationScope) return false;
          if (routingFilters.destinationScopeId && item.destinationScopeId !== routingFilters.destinationScopeId) return false;
          if (routingFilters.status && item.status !== routingFilters.status) return false;
          return true;
        }).slice(0, requestedLimit(query, 50));
        return {ok:true,schemaVersion:"memoryendpoints.routing_decisions.v1",items:clone(matchedDecisions),count:matchedDecisions.length,filters:routingFilters,operatorSummary:{count:matchedDecisions.length,filters:routingFilters,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "POST /api/matm/routing-decisions") {
        var sourceRoomId=body.sourceRoomId||body.source_room_id||body.roomId||body.room_id||"";
        var destinationRoomId=body.destinationRoomId||body.destination_room_id||"";
        var sourceRoom=repository.rooms.filter(function(item){return item.roomId===sourceRoomId;})[0];
        var destinationRoom=repository.rooms.filter(function(item){return item.roomId===destinationRoomId;})[0];
        if(!sourceRoom||!destinationRoom)return resourceFailure("meeting room","");
        var decision={routingDecisionId:"mock-routing-created-"+(repository.routingDecisions.length+1),sourceRoomId:sourceRoom.roomId,routedAgentId:body.routedAgentId||body.routed_agent_id,destinationRoomId:destinationRoom.roomId,destinationScope:destinationRoom.scope,destinationScopeId:destinationRoom.scopeId,coordinatorAgentId:body.coordinatorAgentId||body.coordinator_agent_id||body.actorAgentId||body.actor_agent_id,lane:body.lane,specificGoal:body.specificGoal||body.specific_goal,nextAction:body.nextAction||body.next_action,status:"active",createdAt:"Demo sequence created",valuesRedacted:true};
        repository.routingDecisions.unshift(decision);
        return {ok:true,routingDecision:clone(decision),decision:clone(decision),persisted:true,visibleToAgent:true,operatorSummary:{routingDecisionId:decision.routingDecisionId,rawPayloadExposed:false,rawCredentialExposed:false},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "GET /api/matm/current-message" || key === "GET /api/matm/agent-inbox") {
        var requestedAgentId=query.get("agent_id")||query.get("agentId")||agentId;
        var visibleNotifications=repository.notifications.filter(function(item){return !item.targetAgentId||item.targetAgentId===requestedAgentId;});
        var inbox=visibleNotifications.map(function(item){return {message:{messageId:item.messageId,senderAgentId:item.senderAgentId,targetAgentId:item.targetAgentId,safeSummary:item.safeSummary,responseRequired:item.responseRequired,valuesRedacted:true,createdAt:item.createdAt},notification:{notificationId:item.notificationId,targetAgentId:item.targetAgentId,status:item.read?"read":"unread",responseDisposition:item.responseDisposition},delivery:{messageType:item.targetAgentId?"targeted":"broadcast",targetAgentId:item.targetAgentId,responseDisposition:item.responseDisposition,inboxAgentId:requestedAgentId}};});
        var unreadNotifications=visibleNotifications.filter(function(item){return !item.read;});
        var deliveryCounts={broadcast:visibleNotifications.filter(function(item){return !item.targetAgentId;}).length,targeted:visibleNotifications.filter(function(item){return Boolean(item.targetAgentId);}).length};
        var responseDispositionCounts={required_response:visibleNotifications.filter(function(item){return item.responseRequired;}).length,viewed_acknowledgement:visibleNotifications.filter(function(item){return !item.responseRequired;}).length};
        return {ok:true,items:inbox,count:inbox.length,unreadCount:unreadNotifications.length,totalUnreadCount:unreadNotifications.length,deliveryCounts:deliveryCounts,responseDispositionCounts:responseDispositionCounts,operatorSummary:{agentId:requestedAgentId,unreadCount:unreadNotifications.length,totalUnreadCount:unreadNotifications.length,deliveryCounts:deliveryCounts,responseDispositionCounts:responseDispositionCounts},mockData:true};
      }
      if (key === "POST /api/matm/agent-messages") { var index=repository.notifications.length+1; var notification={notificationId:"mock-notification-created-"+index,messageId:"mock-message-created-"+index,senderAgentId:body.senderAgentId||agentId,targetAgentId:body.targetAgentId||"",safeSummary:(body.safeSummary||"")+" (Mock)",responseRequired:Boolean(body.responseRequired),responseDisposition:body.responseRequired?"required_response":"viewed_acknowledgement",read:false,createdAt:"Demo session"}; repository.notifications.unshift(notification); return {ok:true,message:{messageId:notification.messageId,targetAgentId:notification.targetAgentId,safeSummary:notification.safeSummary},notification:clone(notification),messageId:notification.messageId,notificationId:notification.notificationId,expectedRecipientCount:1,visibleRecipientCount:1,visibleToTarget:true,persisted:true,operatorSummary:{messageType:notification.targetAgentId?"targeted":"broadcast",targetAgentId:notification.targetAgentId,recipientCount:1,deliveryCounts:{broadcast:notification.targetAgentId?0:1,targeted:notification.targetAgentId?1:0},responseDisposition:notification.responseDisposition,responseDispositionCounts:{required_response:body.responseRequired?1:0,viewed_acknowledgement:body.responseRequired?0:1},rawPayloadExposed:false,rawCredentialExposed:false},mockData:true}; }
      if (key === "POST /api/matm/notifications/ack") { var target=repository.notifications.filter(function(item){return item.notificationId===body.notificationId;})[0]; if(!target)return resourceFailure("notification",body.notificationId); target.read=true; var receipt={receiptId:"mock-receipt-created-"+(repository.receipts.length+1),notificationId:body.notificationId,status:"read",consumerAgentId:body.consumerAgentId||agentId,valuesRedacted:true,rawPayloadExposed:false,createdAt:"Demo session"}; repository.receipts.unshift(receipt); return {ok:true,receipt:clone(receipt),persisted:true,operatorSummary:{statusCounts:{read:1},allPayloadsHidden:true,rawPayloadExposedCount:0,rawCredentialExposed:false},mockData:true}; }
      if (key === "GET /api/matm/receipts") {
        var receiptFilters = compactFilters({consumerAgentId:queryValue(query,["consumer_agent_id","consumerAgentId"])});
        var matchedReceipts = repository.receipts.filter(function(item){return !receiptFilters.consumerAgentId||item.consumerAgentId===receiptFilters.consumerAgentId;});
        return {ok:true,items:clone(matchedReceipts),count:matchedReceipts.length,filters:receiptFilters,operatorSummary:{count:matchedReceipts.length,filters:receiptFilters,statusCounts:countBy(matchedReceipts,"status","unknown"),allPayloadsHidden:matchedReceipts.every(function(item){return item.rawPayloadExposed!==true;}),rawPayloadExposedCount:matchedReceipts.filter(function(item){return item.rawPayloadExposed===true;}).length,payloadHidden:true,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "GET /api/matm/audit-log") {
        return {ok:false,safeNoOp:true,visibility:"human_only",agentsCanAccess:false,retentionDays:7,physicallyDeletedAfterRetention:true,error:{code:"human_owner_required",title:"Human owner required",detail:"Routine logs are never available to agents.",safeNoOp:true,valuesRedacted:true},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      }
      if (key === "GET /api/matm/sync/capabilities") return {ok:true,capabilities:{conflictSafe:true,receipts:true},routes:{devices:"/api/matm/sync/devices",mutations:"/api/matm/sync/mutations",receipts:"/api/matm/sync/receipts",changes:"/api/matm/sync/changes",heads:"/api/matm/sync/heads"},mockData:true};
      if (key === "GET /api/matm/sync/retention") return {ok:true,policy:{schemaVersion:"memoryendpoints.sync_retention.v1",tombstoneRetentionDays:30,hardForgetSupported:false,hardForgetBehavior:"safe_rejected_receipt",rawPrivatePayloadStored:false,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false},capabilities:{conflictSafe:true,receipts:true,hardForgetSupported:false},valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,mockData:true};
      if (key === "POST /api/matm/sync/devices" || key === "POST /api/matm/sync/devices/rotate" || key === "POST /api/matm/sync/devices/revoke") {
        var action=key.slice(key.lastIndexOf("/")+1);
        if(action==="devices") action="register";
        var requestedDeviceId=body.deviceId||body.device_id||"";
        if(action!=="register"&&(!repository.syncDevice||!requestedDeviceId||repository.syncDevice.deviceId!==requestedDeviceId))return resourceFailure("sync device","");
        if(action==="register")repository.syncDevice={deviceId:requestedDeviceId||"mock-device-memoryendpoints-ui",agentId:body.agentId||body.agent_id||agentId,label:(body.label||"MemoryEndpoints tour device")+" (Mock)",authorityEpoch:1,status:"active",valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,createdAt:"Demo session"};
        if(action==="rotate")repository.syncDevice.authorityEpoch+=1;
        if(action==="revoke")repository.syncDevice.status="revoked";
        return {ok:true,device:clone(repository.syncDevice),persisted:true,deviceAuthorityPersisted:true,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,operatorSummary:{action:action,status:repository.syncDevice.status,authorityEpoch:repository.syncDevice.authorityEpoch,rawPayloadExposed:false,rawCredentialExposed:false},mockData:true};
      }
      if (key === "POST /api/matm/sync/mutations") {
        var mutationDeviceId=body.deviceId||body.device_id||"";
        if(!repository.syncDevice||!mutationDeviceId||repository.syncDevice.deviceId!==mutationDeviceId)return resourceFailure("sync device","");
        var sequence=repository.syncRevisions.length+1;
        var logicalMemoryId=body.logicalMemoryId||body.logical_memory_id;
        var revision={syncRevisionId:"mock-sync-revision-"+sequence,logicalMemoryId:logicalMemoryId,operation:body.operation||"upsert",memoryType:body.memoryType||body.memory_type||"status",summary:(body.summary||"")+" (Mock)",serverSequence:sequence,deviceId:mutationDeviceId,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
        var syncReceipt={receiptId:"mock-sync-receipt-"+sequence,syncRevisionId:revision.syncRevisionId,logicalMemoryId:revision.logicalMemoryId,status:"applied",serverSequence:sequence,conflict:false,idempotencyKeyExposed:false,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
        repository.syncRevisions.push(revision);repository.syncReceipt=syncReceipt;
        return {ok:true,status:"applied",receipt:clone(syncReceipt),revision:clone(revision),serverSequence:sequence,head:{headRevisionId:revision.syncRevisionId,logicalMemoryId:revision.logicalMemoryId},persisted:true,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false,confirmation:{persisted:true,receiptVisible:true,revisionVisibleInChanges:true,headVisible:true},receiptQueryUrl:"/api/matm/sync/receipts?receipt_id="+syncReceipt.receiptId,changesQueryUrl:"/api/matm/sync/changes?after_sequence=0",headsQueryUrl:"/api/matm/sync/heads?logical_memory_id="+revision.logicalMemoryId,operatorSummary:{rawPayloadExposed:false,rawCredentialExposed:false},mockData:true};
      }
      if (key === "GET /api/matm/sync/receipts") return {ok:true,receipt:clone(repository.syncReceipt||{}),items:repository.syncReceipt?[clone(repository.syncReceipt)]:[],count:repository.syncReceipt?1:0,mockData:true};
      if (key === "GET /api/matm/sync/changes") return {ok:true,items:clone(repository.syncRevisions),changes:clone(repository.syncRevisions),count:repository.syncRevisions.length,indexedThroughSequence:repository.syncRevisions.length,mockData:true};
      if (key === "GET /api/matm/sync/heads") { var latest=repository.syncRevisions[repository.syncRevisions.length-1]; return {ok:true,items:latest?[{headRevisionId:latest.syncRevisionId,logicalMemoryId:latest.logicalMemoryId,serverSequence:latest.serverSequence}]:[],count:latest?1:0,mockData:true}; }
      if (key === "GET /api/matm/knowledge-tree") return {ok:true,mockData:true,tree:{levels:[{scope:"company",scopeId:workspace.companyId,categories:[{category:"ecosystem",documentCount:1,documents:[clone(repository.documents[2])]}]},{scope:"workspace",scopeId:workspace.workspaceId,categories:[{category:"governance",documentCount:1,documents:[clone(repository.documents[1])]}]},{scope:"project",scopeId:workspace.primaryProjectId,categories:[{category:"architecture",documentCount:1,documents:[clone(repository.documents[0])]}]}]}};
      if (key === "GET /api/matm/knowledge-documents") {
        var knowledgeFilters={
          q:queryValue(query,["q","query"]),
          scope:queryValue(query,["scope"]),
          scopeId:queryValue(query,["scope_id","scopeId"]),
          category:queryValue(query,["category"]),
          documentType:queryValue(query,["document_type","documentType","type"]),
          knowledgeStatus:queryValue(query,["knowledge_status","knowledgeStatus","status"]),
          authorityLevel:queryValue(query,["authority_level","authorityLevel","authority"]),
          taxonomyPath:queryValue(query,["taxonomy_path","taxonomyPath","taxonomy_prefix","taxonomyPrefix"]),
          sourcePrefix:queryValue(query,["source_prefix","sourcePrefix"]),
          documentId:queryValue(query,["document_id","documentId","search_document_id","searchDocumentId"]),
          routeOrPath:queryValue(query,["route_or_path","routeOrPath"])
        };
        var activeKnowledgeFilters=compactFilters(knowledgeFilters);
        var knowledgeTerm=knowledgeFilters.q.toLowerCase();
        var matchedDocuments=repository.documents.filter(function(item){
          if(knowledgeTerm&&JSON.stringify(item).toLowerCase().indexOf(knowledgeTerm)===-1)return false;
          if(knowledgeFilters.scope&&item.scope!==knowledgeFilters.scope)return false;
          if(knowledgeFilters.scopeId&&item.scopeId!==knowledgeFilters.scopeId)return false;
          if(knowledgeFilters.category&&item.category!==knowledgeFilters.category)return false;
          if(knowledgeFilters.documentType&&item.documentType!==knowledgeFilters.documentType)return false;
          if(knowledgeFilters.knowledgeStatus&&item.knowledgeStatus!==knowledgeFilters.knowledgeStatus)return false;
          if(knowledgeFilters.authorityLevel&&item.authorityLevel!==knowledgeFilters.authorityLevel)return false;
          if(knowledgeFilters.taxonomyPath&&(item.taxonomyPathLabels||[]).join("/").toLowerCase().indexOf(knowledgeFilters.taxonomyPath.toLowerCase())!==0)return false;
          if(knowledgeFilters.sourcePrefix&&String(item.routeOrPath||"").indexOf(knowledgeFilters.sourcePrefix)!==0)return false;
          if(knowledgeFilters.documentId&&item.searchDocumentId!==knowledgeFilters.documentId)return false;
          if(knowledgeFilters.routeOrPath&&item.routeOrPath!==knowledgeFilters.routeOrPath)return false;
          return true;
        }).slice(0,requestedLimit(query,50));
        var includeText=/^(1|true|yes|on)$/i.test(queryValue(query,["include_text","includeText"]));
        var visibleDocuments=clone(matchedDocuments);
        if(!includeText)visibleDocuments.forEach(function(item){delete item.searchableText;});
        var knowledgeSummary={schemaVersion:"memoryendpoints.knowledge_operator_summary.v2",documentCount:visibleDocuments.length,scopeCounts:countBy(visibleDocuments,"scope","unknown"),categoryCounts:countBy(visibleDocuments,"category","uncategorized"),knowledgeStatusCounts:countBy(visibleDocuments,"knowledgeStatus","current"),authorityLevelCounts:countBy(visibleDocuments,"authorityLevel","reviewed"),filters:activeKnowledgeFilters,databaseSourceOfTruth:true,filesystemDocsIncluded:false,taskLevelTreeSupported:false,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
        return {ok:true,items:visibleDocuments,count:visibleDocuments.length,filters:activeKnowledgeFilters,operatorSummary:knowledgeSummary,knowledgeSource:"database_search_documents",filesystemDocsIncluded:false,includeText:includeText,mockData:true,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
      }
      if (key === "GET /api/matm/external-links" || key === "GET /api/matm/internet-search") {
        var linkFilters={q:queryValue(query,["q","query"]),documentId:queryValue(query,["document_id","documentId","knowledge_document_id","knowledgeDocumentId"]),host:queryValue(query,["host"]),siteName:queryValue(query,["site_name","siteName"])};
        var activeLinkFilters=compactFilters(linkFilters);
        var linkTerm=linkFilters.q.toLowerCase();
        var matchedLinks=repository.links.filter(function(item){
          if(linkFilters.documentId&&linkFilters.documentId!=="mock-knowledge-ecosystem")return false;
          if(linkTerm&&JSON.stringify(item).toLowerCase().indexOf(linkTerm)===-1)return false;
          if(linkFilters.host&&item.host!==linkFilters.host)return false;
          if(linkFilters.siteName&&item.siteName!==linkFilters.siteName)return false;
          return true;
        }).slice(0,requestedLimit(query,50));
        return {ok:true,items:clone(matchedLinks),count:matchedLinks.length,filters:activeLinkFilters,operatorSummary:{resultCount:matchedLinks.length,filters:activeLinkFilters,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false},mockData:true,valuesRedacted:true,rawCredentialExposed:false,rawPayloadExposed:false};
      }
      return null;
    }

    return {
      request: function (path, requestOptions) {
        var options=requestOptions===undefined?{}:requestOptions;
        var descriptor;
        try {
          descriptor=requestKey(path,options);
        } catch (error) {
          return Promise.reject(error && error.safeNoOp === true ? error : safeError("mock_invalid_request"));
        }
        var payload=response(descriptor,options);
        if(payload===null)return rejectUnknown(descriptor.key);
        if(payload&&payload.__mockReject)return Promise.reject(safeError(payload.code));
        return Promise.resolve(clone(payload));
      },
      reset: function () { repository=createRepository(); },
      snapshot: function () { return clone(repository); }
    };
  }

  root.MemoryEndpointsMockTransport = {
    bootstrap: function () {
      return {
        agentId: "MemoryEndpoints-Frontend-Agent",
        workspaceId: "mock-workspace-memoryendpoints-tour",
        initialKnowledgeDocumentId: "mock-knowledge-overview"
      };
    },
    create:create
  };
})(typeof window !== "undefined" ? window : globalThis);
