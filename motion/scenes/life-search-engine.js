/* Where Did I Eat in Chicago, and Who Was There? Left: right receipt found, 291 questions (Walking the graph in hops 92.8%; One vector search 8.9%).
   Right: Right restaurant 93.8%; Right people, exactly 79.4%; Questions 291. Every figure is on the project page. */
scene({
  slug: "life-search-engine", aspect: 1.72, seconds: 6, bg: ["#0f1114", "#040405"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "RIGHT RECEIPT FOUND, 291 QUESTIONS",
    bars: [["Walking the graph in hops", 92.8, "92.8%"], ["One vector search", 8.9, "8.9%"]],
    stats: [["Right restaurant", "93.8%", "#4a95f0"], ["Right people, exactly", "79.4%", "#4a95f0"], ["Questions", "291"]],
  }),
});
