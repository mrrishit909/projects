/* What Does Entanglement Look Like Gate by Gate? Left: grover-3, chance of the marked item, % (Ideal simulation 94.5; Mock 5-qubit device, 10 SWAPs 39.9; Lab default noise 30.2).
   Right: Bell pair entanglement 0.50; Rust/WASM vs TypeScript 2.5–2.8×; SWAPs inserted 10; GHZ pairs entangled 0. Every figure is on the project page. */
scene({
  slug: "quantum-circuit-lab", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "GROVER-3, CHANCE OF THE MARKED ITEM, %",
    bars: [["Ideal simulation", 94.5, "94.5", "#4a95f0"], ["Mock 5-qubit device, 10 SWAPs", 39.9, "39.9", "#ff8a3d"], ["Lab default noise", 30.2, "30.2", "#8a8f98"]],
    stats: [["Bell pair entanglement", "0.50", "#4a95f0"], ["Rust/WASM vs TypeScript", "2.5–2.8×", "#4a95f0"], ["SWAPs inserted", "10", "#ff8a3d"], ["GHZ pairs entangled", "0", "#8a8f98"]],
  }),
});
