/* How Sure Can Anyone Be About a Motion? Left: ranking score: will the motion be granted? (This model 0.741; Judge's rate alone 0.727; Motion base rate 0.650; Knowing the truth 0.788).
   Right: Error, this model 0.206; Error, judge's rate alone 0.211; Stated range held the truth 40%. Every figure is on the project page. */
scene({
  slug: "court-analytics", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RANKING SCORE: WILL THE MOTION BE GRANTED?",
    bars: [["This model", 0.741, "0.741"], ["Judge's rate alone", 0.727, "0.727"], ["Motion base rate", 0.65, "0.650"], ["Knowing the truth", 0.788, "0.788", "#8a8f98"]],
    stats: [["Error, this model", "0.206", "#4a95f0"], ["Error, judge's rate alone", "0.211", "#ff8a3d"], ["Stated range held the truth", "40%", "#ff8a3d"]],
  }),
});
