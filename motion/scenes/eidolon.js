/* What Does One Mesh Look Like Across Seven Garment Stages? Left: drape percent by fabric at Runway (Chiffon 94; Silk 88; Wool 62; Denim 38).
   Right: Draw calls, full scene 5; Garment stages, Thread to Runway 7; Fabric swatches 4; Garment triangles 2,204. Every figure is on the project page. */
scene({
  slug: "eidolon", aspect: 1.72, seconds: 6, bg: ["#171310", "#090909"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DRAPE % AT RUNWAY, BY FABRIC",
    bars: [["Chiffon", 94, "94", "#EAE4DA"], ["Silk", 88, "88", "#D7B9A3"], ["Wool", 62, "62", "#6A5CFF"], ["Denim", 38, "38", "#233544"]],
    stats: [["Draw calls, full scene", "5", "#B7112C"], ["Garment stages", "7", "#D7B9A3"], ["Fabric swatches", "4", "#6A5CFF"], ["Garment triangles", "2,204", "#8a8f98"]],
  }),
});
