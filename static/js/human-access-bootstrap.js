(function () {
  "use strict";

  function mount() {
    var root = document.querySelector("[data-human-access]");
    var api = window.MemoryEndpointsHumanAccess;
    if (!root || !api) return;
    var demoMode = root.hasAttribute("data-human-access-demo");
    var preauthOnly = root.hasAttribute("data-human-access-preauth-only");
    var localAutoLogin = root.hasAttribute("data-human-access-local-auto-login");
    var options = {
      root: root,
      demoMode: demoMode,
      preauthOnly: preauthOnly,
      navigate: function (path) { window.location.assign(path); }
    };
    if (demoMode) {
      options.transport = api.createDemoTransport();
      options.sessionAuthority = api.createSessionAuthority();
    }
    var controller = api.create(options);
    controller.mount();
    if (preauthOnly && localAutoLogin && !demoMode) controller.loginLocalComputer();
    else if (!preauthOnly && !demoMode) controller.revalidateHumanSession();
    window.MemoryEndpointsHumanAccessController = controller;
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount, {once: true});
  else mount();
})();
