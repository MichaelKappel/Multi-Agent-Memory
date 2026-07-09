(function () {
  var badges = [{ selector: ".brand span", text: "MemoryEndpoints.com" }];
  for (var i = 0; i < badges.length; i += 1) {
    var node = document.querySelector(badges[i].selector);
    if (node && node.textContent !== badges[i].text) {
      node.textContent = badges[i].text;
    }
  }
})();
