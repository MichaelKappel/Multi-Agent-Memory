(function () {
  "use strict";

  function protectedReturnPath(pathname) {
    if (pathname === "/console" || pathname === "/knowledge" || String(pathname || "").indexOf("/knowledge/") === 0) {
      return pathname;
    }
    return "/human";
  }

  function mount() {
    var root = document.querySelector("[data-human-access]");
    var api = window.MemoryEndpointsHumanAccess;
    if (!root || !api) return;
    var demoMode = root.hasAttribute("data-human-access-demo");
    var preauthOnly = root.hasAttribute("data-human-access-preauth-only");
    var options = {
      root: root,
      demoMode: demoMode,
      preauthOnly: preauthOnly,
      returnPath: protectedReturnPath(window.location.pathname),
      navigate: function (path) { window.location.assign(path); }
    };
    if (demoMode) {
      options.transport = api.createDemoTransport();
      options.sessionAuthority = api.createSessionAuthority();
    }
    var controller = api.create(options);
    controller.mount();
    if (!preauthOnly && !demoMode) controller.revalidateHumanSession();
    window.MemoryEndpointsHumanAccessController = controller;
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once: true});
  else mount();
})();
