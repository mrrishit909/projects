/* Who Moves When an Aisle Closes? Left: travel per order on the same 7.5-minute peak shift (FIFO nearest-free 77.9 cells;
   CP-SAT dispatch 63.7). Right: Collisions in 4,050,000 robot-steps 0; Local re-plan after a stop, p95 204 ms;
   Urgent orders on time with preemption 5 of 5 vs 3 of 5; Travel saved when the fleet keeps up 1.7–2.0%.
   Every figure is on the project page. */
scene({
  slug: "warehouse-robot-orchestration", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TRAVEL PER ORDER, SAME PEAK SHIFT (CELLS OF 1.2 M)",
    bars: [["FIFO nearest-free", 77.9, "77.9", "#8a8f98"], ["CP-SAT dispatch", 63.7, "63.7", "#4a95f0"]],
    stats: [["Collisions in 4,050,000 robot-steps", "0", "#4a95f0"], ["Local re-plan after a stop, p95", "204 ms", "#4a95f0"], ["Urgent orders on time with preemption", "5 of 5 vs 3 of 5", "#4a95f0"], ["Travel saved when the fleet keeps up", "1.7–2.0%", "#ff8a3d"]],
  }),
});
