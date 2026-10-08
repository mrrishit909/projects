/* What Breaks When You Put Real Optics Formulas On White? Left: reflectance percent by incidence angle (0deg 4.0; 30deg 4.4; 60deg 10.3; 80deg 41.0).
   Right: Draw calls, full scene 7; Optical phenomena, Reflection to Aberration 6; Malus transmission at 45deg 50%; LCP, fastest in the volume 1.7s. Every figure is on the project page. */
scene({
  slug: "lucent", aspect: 1.72, seconds: 6, bg: ["#f3f3ee", "#fbfbf7"],
  draw: (g, u, W, H, S, T) => T.versus(g, u, W, H, {
    kicker: "REFLECTANCE % BY INCIDENCE ANGLE",
    bars: [["0 deg", 4.0, "4.0", "#00D9FF"], ["30 deg", 4.4, "4.4", "#00D9FF"], ["60 deg", 10.3, "10.3", "#FFC942"], ["80 deg", 41.0, "41.0", "#FF3855"]],
    stats: [["Draw calls, full scene", "7", "#7B61FF"], ["Phenomena modeled", "6", "#00D9FF"], ["Malus transmission at 45deg", "50%", "#FF3855"], ["LCP, fastest in the volume", "1.7s", "#8a8f98"]],
  }),
});
