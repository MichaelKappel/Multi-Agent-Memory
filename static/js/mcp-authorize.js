(function () {
  "use strict";

  var form = document.querySelector("[data-mcp-login]");
  if (!form) {
    return;
  }
  var status = form.querySelector("[data-mcp-login-status]");
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var submit = form.querySelector("button[type=submit]");
    var password = form.elements.password;
    submit.disabled = true;
    status.textContent = "Signing in…";
    fetch("/oauth/session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.elements.username.value,
        password: password.value
      })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok || !payload.ok) {
          throw new Error("Sign-in was not completed. Check the username and password.");
        }
        password.value = "";
        status.textContent = "Signed in. Loading approval…";
        window.location.reload();
      });
    }).catch(function (error) {
      password.value = "";
      submit.disabled = false;
      status.textContent = error.message || "Sign-in was not completed.";
      password.focus();
    });
  });
}());
