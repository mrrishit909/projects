/* Which of 40,000 Drive Units Hold a Bad Capacitor? Left: affected units the recall leaves out, scored on the truth (MES serial genealogy 492; Every unit built while B-177 was on a line 475; Model: minimum defensible set 0).
   Right: Units to recall 2,874; Cost vs the broad recall $444k vs $1,478k; Returns, B-177 vs the rest 4.7×; Rework tickets without the board 343. Every figure is on the project page. */
scene({
  slug: "product-recall-traceability", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "AFFECTED UNITS THE RECALL LEAVES OUT, SCORED ON THE TRUTH",
    bars: [["MES serial genealogy", 492, "492"], ["Every unit built while B-177 was on a line", 475, "475"], ["Model: minimum defensible set", 0, "0", "#8a8f98"]],
    stats: [["Units to recall", "2,874", "#4a95f0"], ["Cost vs the broad recall", "$444k vs $1,478k", "#ff8a3d"], ["Returns, B-177 vs the rest", "4.7×", "#ff8a3d"], ["Rework tickets without the board", "343", "#8a8f98"]],
  }),
});
