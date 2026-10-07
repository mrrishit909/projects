/* How Tilted Can an Orbit Be Before the Shadow Disappears? Left: transit dip of an 11 Earth-radius planet on a 5-day orbit, ppm (at 89.9 degrees 11,734; at 84 degrees 0).
   Right: Impact parameter at 84 degrees 1.29; NEB-017 c temperature now 804 K; in the habitable zone 222 K; Earth similarity 0.096 then 0.761. Every figure is on the project page. */
scene({
  slug: "nebula-exoplanet-lab", aspect: 1.72, seconds: 6, bg: ["#100d1c", "#06050a"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "TRANSIT DEPTH, PPM",
    bars: [["Inclination 89.9 degrees", 11734, "11,734", "#EE3D8A"], ["Inclination 84 degrees", 0, "0", "#7B4DFF"]],
    stats: [["Impact parameter at 84 degrees", "1.29", "#FF7A1A"], ["NEB-017 c, now", "804 K", "#FF7A1A"], ["NEB-017 c, in the habitable zone", "222 K", "#7B4DFF"], ["Earth similarity, now to there", "0.096 to 0.761", "#FFF4D9"]],
  }),
});
