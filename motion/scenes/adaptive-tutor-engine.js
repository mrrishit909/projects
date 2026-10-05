/* What Should This Student Do Next? Left: concepts mastered, 300 simulated students (Adaptive 10.6; Fixed lesson order 4.4).
   Right: Still known two weeks later 7.8 vs 2.7; Misconceptions left 0.02 vs 0.89; Answers to diagnose one 6. Every figure is on the project page. */
scene({
  slug: "adaptive-tutor-engine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "CONCEPTS MASTERED, 300 SIMULATED STUDENTS",
    bars: [["Adaptive", 10.6, "10.6"], ["Fixed lesson order", 4.4, "4.4"]],
    stats: [["Still known two weeks later", "7.8 vs 2.7", "#4a95f0"], ["Misconceptions left", "0.02 vs 0.89", "#4a95f0"], ["Answers to diagnose one", "6"]],
  }),
});
