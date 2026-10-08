/* What Does One Painting Look Like Under Seven Kinds of Light? Left: damage-region confidence percent (Craquelure 89; Tear repair 89; Overpaint 61; Flaking 59).
   Right: Draw calls, full scene 9; Imaging modalities, one shader 7; Painting triangles 136; Damage regions tracked 5. Every figure is on the project page. */
scene({
  slug: "tessera", aspect: 1.72, seconds: 6, bg: ["#141a2e", "#0a0d1a"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DAMAGE-REGION CONFIDENCE, PERCENT",
    bars: [["Craquelure", 89, "89", "#C6A15B"], ["Tear repair", 89, "89", "#C6A15B"], ["Overpaint", 61, "61", "#587061"], ["Flaking", 59, "59", "#922F39"]],
    stats: [["Draw calls, full scene", "9", "#C6A15B"], ["Imaging modalities", "7", "#587061"], ["Painting triangles", "136", "#DED1B7"], ["Damage regions tracked", "5", "#8a8f98"]],
  }),
});
