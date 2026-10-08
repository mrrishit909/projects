/* What Does One Wind-Shaped Formula Do to 18 Houses? Left: structure risk at T+12h (Residence 14 100; Residence 17 93; Residence 4 83; Residence 18 33).
   Right: Draw calls, full scene 3; Structures tracked 18; Trees instanced, one draw call 160; Suppression risk discount 50%. Every figure is on the project page. */
scene({
  slug: "ember", aspect: 1.72, seconds: 6, bg: ["#241a12", "#11100F"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "STRUCTURE RISK AT T+12H",
    bars: [["Residence 14", 100, "100", "#F04A23"], ["Residence 17", 93, "93", "#F04A23"], ["Residence 4", 83, "83", "#FFB33A"], ["Residence 18", 33, "33", "#233A29"]],
    stats: [["Draw calls, full scene", "3", "#FFB33A"], ["Structures tracked", "18", "#F1EEE7"], ["Trees, one draw call", "160", "#233A29"], ["Suppression risk discount", "50%", "#8a8f98"]],
  }),
});
