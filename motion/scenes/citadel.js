/* What Happens to 1,000 People When One Exit Closes? Left: gate flow per minute at emergency (Gate A 0; Gate D 87; Gate B 115; Gate C 144).
   Right: Draw calls, full scene 34; Gates on the concourse 8; Crowd glyphs, one draw call 320; Redistributed flow share 1/7. Every figure is on the project page. */
scene({
  slug: "citadel", aspect: 1.72, seconds: 6, bg: ["#141c26", "#101417"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "GATE FLOW AT EMERGENCY, PER MIN",
    bars: [["Gate A", 0, "0", "#D32F2F"], ["Gate D", 87, "87", "#79838B"], ["Gate B", 115, "115", "#B9FF44"], ["Gate C", 144, "144", "#B9FF44"]],
    stats: [["Draw calls, full scene", "34", "#B9FF44"], ["Gates on the concourse", "8", "#183B66"], ["Crowd glyphs, one draw call", "320", "#F3F1EA"], ["Redistributed flow share", "1/7", "#8a8f98"]],
  }),
});
