/* Which Claim Can Show Its Source? Left: tokens read, one run (Corpus in the window 206,585; Registry records, if sent 86,748; Synthesizer, opus 7,339; Escalated 2×2 table, opus 65).
   Right: Cost per run $0.64; Claims flagged by the critic 3 of 7; Escalations 1 of 7 agents; Papers kept of 423 58. Every figure is on the project page. */
scene({
  slug: "helix-research-workspace", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TOKENS READ, ONE RUN",
    bars: [["Corpus in the window", 206585, "206,585", "#8a8f98"], ["Registry records, if sent", 86748, "86,748", "#8a8f98"], ["Synthesizer, opus", 7339, "7,339", "#ff8a3d"], ["Escalated 2×2 table, opus", 65, "65", "#ff8a3d"]],
    stats: [["Cost per run", "$0.64", "#ff8a3d"], ["Claims flagged by the critic", "3 of 7", "#ff8a3d"], ["Escalations", "1 of 7 agents", "#8a8f98"], ["Papers kept of 423", "58", "#8a8f98"]],
  }),
});
