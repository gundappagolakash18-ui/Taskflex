const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#ec4899", "#f97316"];

export function celebrate(): void {
  if (typeof document === "undefined") return;
  const root = document.createElement("div");
  root.className = "pointer-events-none fixed inset-0 z-[120] overflow-hidden";
  root.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 80; i += 1) {
    const piece = document.createElement("span");
    piece.className = "tf-confetti";
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = COLORS[i % COLORS.length];
    piece.style.width = `${6 + Math.random() * 6}px`;
    piece.style.height = `${8 + Math.random() * 8}px`;
    piece.style.animationDelay = `${Math.random() * 0.9}s`;
    piece.style.animationDuration = `${1.9 + Math.random() * 1.2}s`;
    piece.style.setProperty("--tf-drift", `${(Math.random() - 0.5) * 220}px`);
    root.appendChild(piece);
  }
  document.body.appendChild(root);
  window.setTimeout(() => root.remove(), 3400);
}
