/* What Does a Descent Look Like When the Asset Is Built in Blender? Left: download weight, KB (Submersible GLB 100; Seabed kit GLB 52; JS gzipped 565).
   Right: Pressure at 4,100 m 413 bar; Seabed swept by six dives 32.7%; Draw calls in the replay view 47; Vehicle triangles 2,266. Every figure is on the project page. */
scene({
  slug: "abyssal-deep-ocean", aspect: 1.72, seconds: 6, bg: ["#06141c", "#02080d"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "DOWNLOAD WEIGHT, KB",
    bars: [["Submersible GLB", 100, "100", "#13F4EF"], ["Seabed kit GLB", 52, "52", "#13F4EF"], ["JavaScript, gzipped", 565, "565", "#087EFC"]],
    stats: [["Pressure at 4,100 m", "413 bar", "#13F4EF"], ["Seabed swept by six dives", "32.7%", "#9D5CFF"], ["Draw calls, replay view", "47", "#8a8f98"], ["Vehicle triangles", "2,266", "#8a8f98"]],
  }),
});
