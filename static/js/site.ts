type RouteBadge = {
  selector: string;
  text: string;
};

const badges: RouteBadge[] = [
  { selector: ".brand span", text: "MemoryEndpoints.com" },
];

for (const badge of badges) {
  const node = document.querySelector<HTMLElement>(badge.selector);
  if (node && node.textContent !== badge.text) {
    node.textContent = badge.text;
  }
}
