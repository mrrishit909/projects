/* Which Silences at Sea Were on Purpose? Left: ais silences in 48 hours and what flags them (Silences of two hours or more 108; Six-hour rule 33; Gap model 3).
   Right: Rule-breakers in the top ten: model vs silent hours 7 vs 3; Southern Star 7's silence 22.3 h; Distance-only rule meetings 21; Fishing boats 110. Every figure is on the project page. */
scene({
  slug: "fisheries-watch", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "AIS SILENCES IN 48 HOURS AND WHAT FLAGS THEM",
    bars: [["Silences of two hours or more", 108, "108"], ["Six-hour rule", 33, "33", "#4a95f0"], ["Gap model", 3, "3", "#8a8f98"]],
    stats: [["Rule-breakers in the top ten: model vs silent hours", "7 vs 3", "#ff8a3d"], ["Southern Star 7's silence", "22.3 h", "#ff8a3d"], ["Distance-only rule meetings", "21", "#4a95f0"], ["Fishing boats", "110", "#8a8f98"]],
  }),
});
