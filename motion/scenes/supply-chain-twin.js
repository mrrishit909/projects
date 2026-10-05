/* What Does a Three-Week Port Slowdown Cost, and What Is the Cheapest Way Out? Left: total cost of a three-week port slowdown (Optimized plan $0.22M; Do nothing $1.39M; Fly the most delayed $5.39M).
   Right: Lost revenue, do nothing $2.58M; Lost revenue, optimized $0.06M; Freight, optimized $0.18M; Futures simulated 1,000. Every figure is on the project page. */
scene({
  slug: "supply-chain-twin", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TOTAL COST OF A THREE-WEEK PORT SLOWDOWN",
    bars: [["Optimized plan", 0.22, "$0.22M"], ["Do nothing", 1.39, "$1.39M"], ["Fly the most delayed", 5.39, "$5.39M"]],
    stats: [["Lost revenue, do nothing", "$2.58M", "#ff8a3d"], ["Lost revenue, optimized", "$0.06M", "#4a95f0"], ["Freight, optimized", "$0.18M", "#4a95f0"], ["Futures simulated", "1,000"]],
  }),
});
