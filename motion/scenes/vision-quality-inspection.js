/* What Does an Operator's "That Part Was Fine" Teach a Defect Camera? Left: good new-supplier boards rejected (Version 1, before review 100%; Version 2, after 34 corrections 24.0%).
   Right: Labelled defects caught vs template 17 vs 8; Inspection time p99 18.39 ms; Canary rejects vs control 20.3% vs 70.8%; Defects passed by the canary 5 of 29. Every figure is on the project page. */
scene({
  slug: "vision-quality-inspection", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "GOOD NEW-SUPPLIER BOARDS REJECTED",
    bars: [["Version 1, before review", 100, "100%"], ["Version 2, after 34 corrections", 24, "24.0%", "#4a95f0"]],
    stats: [["Labelled defects caught vs template", "17 vs 8", "#8a8f98"], ["Inspection time p99", "18.39 ms", "#4a95f0"], ["Canary rejects vs control", "20.3% vs 70.8%", "#4a95f0"], ["Defects passed by the canary", "5 of 29", "#ff8a3d"]],
  }),
});
