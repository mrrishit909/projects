/* What Does Each Complication Cost the Movement, Not Just the Price? Left: parts in the movement (Plain 112; + date 133; + date and moon 167; + all three 185).
   Right: Thickness with all three 10.2 mm; Power reserve with all three 65 h; Named parts in the contract 27; Base price, fictional $4,800. Every figure is on the project page. */
scene({
  slug: "vitra-watch-atelier", aspect: 1.72, seconds: 6, bg: ["#12100b", "#050505"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "PARTS IN THE MOVEMENT",
    bars: [["Plain movement", 112, "112", "#B7C0C7"], ["With date", 133, "133", "#D7BA75"], ["With date and moon", 167, "167", "#D7BA75"], ["With all three", 185, "185", "#A6112D"]],
    stats: [["Thickness, all three", "10.2 mm", "#D7BA75"], ["Power reserve, all three", "65 h", "#A6112D"], ["Named parts in the contract", "27", "#8a8f98"], ["Base price, fictional", "$4,800", "#8a8f98"]],
  }),
});
